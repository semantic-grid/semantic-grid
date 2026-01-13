"""FastMCP server for db-meta-v2."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from pydantic_ai import Agent
from starlette.requests import Request
from starlette.responses import JSONResponse

from db_meta_v2.config import get_settings
from db_meta_v2.tasks.store import get_task_store
from db_meta_v2.tools.database import (
    _describe_table,
    _detect_dialect,
    _list_catalogs,
    _list_schemas,
    _list_tables,
    _sample_table,
    _test_connection,
)
from db_meta_v2.tools.dialect import _get_connection_dialect, _get_dialect_rules
from db_meta_v2.tools.domain import (
    _domain_approve,
    _domain_generate,
    _domain_skip,
    _domain_status,
)
from db_meta_v2.tools.generation import (
    _export_results,
    _get_data,
    _get_result,
    _run_sql,
    _test_elicitation,
    _test_sampling,
    _validate_sql,
)
from db_meta_v2.tools.onboarding import (
    _onboarding_add_ignore_pattern,
    _onboarding_approve,
    _onboarding_bulk_approve,
    _onboarding_discover,
    _onboarding_import_ignore_patterns,
    _onboarding_next,
    _onboarding_remove_ignore_pattern,
    _onboarding_reset,
    _onboarding_skip,
    _onboarding_start,
    _onboarding_status,
)
from db_meta_v2.tools.shell import (
    SHELL_DESCRIPTION_DETAILED,
    SHELL_DESCRIPTION_SHELL_MODE,
    _protocol,
    _shell,
)
from db_meta_v2.tools.training import (
    _import_examples,
    _import_instructions,
    _query_add_rule,
    _query_approve,
    _query_feedback,
    _query_generate,
    _query_list_examples,
    _query_list_rules,
    _query_status,
)
from db_meta_v2.vault import ensure_vault_structure, migrate_legacy_provider_data


class HealthCheckFilter(logging.Filter):
    """Filter out health check requests from uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        # Filter out GET /health requests
        if "GET /health" in message:
            return False
        return True


# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


def _get_auth_provider():
    """Get auth provider based on config.

    Uses DiskStore on the providers PVC for OAuth client storage, which
    persists sessions across restarts. For HA deployments with multiple
    replicas, consider using RedisStore with FernetEncryptionWrapper.
    """
    settings = get_settings()
    if settings.auth0_enabled and settings.auth0_domain:
        from pathlib import Path

        from fastmcp.server.auth.providers.auth0 import Auth0Provider
        from key_value.aio.stores.disk import DiskStore

        # Use the providers PVC directory for OAuth session storage
        oauth_storage_path = Path(settings.providers_dir) / ".oauth"

        provider = Auth0Provider(
            config_url=f"https://{settings.auth0_domain}/.well-known/openid-configuration",
            client_id=settings.auth0_client_id,
            client_secret=settings.auth0_client_secret,
            audience=settings.auth0_audience,
            base_url=settings.auth0_base_url,
            client_storage=DiskStore(directory=oauth_storage_path),
        )
        # Allow Claude's redirect URI for DCR compatibility
        # See: https://github.com/jlowin/fastmcp/issues/1564
        provider._allowed_client_redirect_uris = [
            "https://claude.ai/api/mcp/auth_callback",
            "http://localhost:*",
            "http://127.0.0.1:*",
        ]
        return provider
    return None


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Server lifespan for startup/shutdown tasks."""
    logger = logging.getLogger(__name__)

    # Startup: Start background task cleanup loop
    task_store = get_task_store()
    await task_store.start_cleanup_loop(interval_seconds=300)  # Every 5 minutes
    logger.info("Task store cleanup loop started")

    try:
        yield
    finally:
        # Shutdown: Stop cleanup loop
        await task_store.stop_cleanup_loop()
        logger.info("Task store cleanup loop stopped")


# =============================================================================
# Server Instructions by Mode
# =============================================================================

INSTRUCTIONS_DETAILED = """
Database metadata and query intelligence server.

## BEFORE ANY QUERY WORK

1. Read the knowledge vault protocol:
   ```
   shell(command="cat PROTOCOL.md")
   ```

2. Check SQL rules for this database:
   ```
   shell(command="cat instructions/sql_rules.md")
   ```

## CRITICAL: Database Hierarchy

Many databases use 3-level hierarchy: `catalog.schema.table`
- Use `list_catalogs()` FIRST if available
- Then `list_schemas(catalog="...")`
- Then `list_tables(catalog="...", schema="...")`

Do NOT skip to schema level - this causes "table not found" errors.

## After Successful Queries

Save examples and tell the user what you saved. See PROTOCOL.md for details.

## Tools Available

- Schema discovery: list_catalogs, list_schemas, list_tables, describe_table
- Query: get_data, run_sql
- Knowledge vault: shell (bash access to examples, learnings, instructions)
- Setup: mcp_setup_*, mcp_domain_*
"""

INSTRUCTIONS_SHELL_MODE = """
Database query server - SHELL-FIRST MODE

## YOU HAVE ONE PRIMARY TOOL: shell

Use `shell` for ALL query preparation. It gives you access to a knowledge vault
containing everything you need: examples, schema, rules, learnings.

## IMMEDIATE FIRST STEP

```
shell(command="cat PROTOCOL.md")
```

This tells you exactly how to:
- Find existing query examples
- Understand the database schema
- Follow SQL rules for this database
- Save successful queries for reuse

## QUERY WORKFLOW

1. shell(command="cat PROTOCOL.md")           # Read the rules
2. shell(command="grep -ri 'keyword' examples/")  # Find similar queries
3. shell(command="cat schema/tables.yaml")    # Understand tables
4. Write SQL based on what you found
5. validate_sql(sql="...")                    # Validate before running
6. run_sql(query_id="...")                    # Execute
7. Save successful queries back to examples/

## OTHER TOOLS

- validate_sql / run_sql / get_result - Query execution (required for running SQL)
- export_results - Export data to CSV/JSON
- mcp_setup_* / mcp_domain_* - Admin setup (not for regular queries)

DO NOT look for other schema discovery tools. Use `shell` to explore the vault.
"""


# =============================================================================
# Server Creation
# =============================================================================


def _create_server() -> FastMCP:
    """Create and configure the MCP server based on tool_mode setting."""
    settings = get_settings()
    is_shell_mode = settings.tool_mode == "shell"

    instructions = INSTRUCTIONS_SHELL_MODE if is_shell_mode else INSTRUCTIONS_DETAILED

    server = FastMCP(
        name="db-meta-v2",
        auth=_get_auth_provider(),
        lifespan=server_lifespan,
        instructions=instructions,
    )

    # =========================================================================
    # MCP Resources - always exposed
    # =========================================================================

    @server.resource("protocol://knowledge-vault")
    def get_protocol() -> str:
        """Knowledge vault protocol - READ THIS FIRST before any query work."""
        protocol_path = Path(settings.vault_path) / "PROTOCOL.md"
        if protocol_path.exists():
            return protocol_path.read_text()
        return "PROTOCOL.md not found. Run vault initialization."

    @server.resource("protocol://sql-rules")
    def get_sql_rules() -> str:
        """SQL generation rules for this database."""
        rules_path = Path(settings.vault_path) / "instructions" / "sql_rules.md"
        if rules_path.exists():
            return rules_path.read_text()
        return "sql_rules.md not found."

    # Health check endpoint for k8s probes
    @server.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        """Health check endpoint for load balancers and k8s probes."""
        return JSONResponse(
            {
                "status": "healthy",
                "service": "db-meta-v2",
                "provider_id": settings.provider_id,
                "tool_mode": settings.tool_mode,
            }
        )

    # =========================================================================
    # Core tools - always available
    # =========================================================================

    async def _ping() -> dict:
        """Health check - verify server is running."""
        return {
            "status": "ok",
            "provider_id": settings.provider_id,
            "tool_mode": settings.tool_mode,
            "database_configured": bool(settings.database_url),
        }

    async def _get_config() -> dict:
        """Get current server configuration (non-sensitive)."""
        return {
            "provider_id": settings.provider_id,
            "tool_mode": settings.tool_mode,
            "resources_dir": settings.resources_dir,
            "providers_dir": settings.providers_dir,
            "database_configured": bool(settings.database_url),
        }

    server.tool(name="ping")(_ping)
    server.tool(name="get_config")(_get_config)

    # =========================================================================
    # Shell tool - with mode-specific description
    # =========================================================================

    shell_description = (
        SHELL_DESCRIPTION_SHELL_MODE if is_shell_mode else SHELL_DESCRIPTION_DETAILED
    )
    server.tool(name="shell", description=shell_description)(_shell)
    server.tool(name="protocol")(_protocol)

    # =========================================================================
    # SQL execution tools - always available
    # =========================================================================

    server.tool(name="validate_sql")(_validate_sql)
    server.tool(name="run_sql")(_run_sql)
    server.tool(name="get_result")(_get_result)
    server.tool(name="export_results")(_export_results)

    # =========================================================================
    # Admin/Setup tools - always available (not for casual query use)
    # =========================================================================

    # MCP setup tools (schema discovery wizard)
    server.tool(name="mcp_setup_status")(_onboarding_status)
    server.tool(name="mcp_setup_start")(_onboarding_start)
    server.tool(name="mcp_setup_add_ignore_pattern")(_onboarding_add_ignore_pattern)
    server.tool(name="mcp_setup_remove_ignore_pattern")(_onboarding_remove_ignore_pattern)
    server.tool(name="mcp_setup_import_ignore_patterns")(_onboarding_import_ignore_patterns)
    server.tool(name="mcp_setup_discover")(_onboarding_discover)
    server.tool(name="mcp_setup_reset")(_onboarding_reset)
    server.tool(name="mcp_setup_next")(_onboarding_next)
    server.tool(name="mcp_setup_approve")(_onboarding_approve)
    server.tool(name="mcp_setup_skip")(_onboarding_skip)
    server.tool(name="mcp_setup_bulk_approve")(_onboarding_bulk_approve)

    # MCP domain tools (domain model generation)
    server.tool(name="mcp_domain_status")(_domain_status)
    server.tool(name="mcp_domain_generate")(_domain_generate)
    server.tool(name="mcp_domain_approve")(_domain_approve)
    server.tool(name="mcp_domain_skip")(_domain_skip)

    # Import tools (bulk import from legacy format)
    server.tool(name="import_instructions")(_import_instructions)
    server.tool(name="import_examples")(_import_examples)

    # =========================================================================
    # Detailed mode ONLY - schema discovery and query helper tools
    # =========================================================================

    if not is_shell_mode:
        # Database introspection tools
        server.tool(name="test_connection")(_test_connection)
        server.tool(name="detect_dialect")(_detect_dialect)
        server.tool(name="list_catalogs")(_list_catalogs)
        server.tool(name="list_schemas")(_list_schemas)
        server.tool(name="list_tables")(_list_tables)
        server.tool(name="describe_table")(_describe_table)
        server.tool(name="sample_table")(_sample_table)

        # Dialect tools
        server.tool(name="get_dialect_rules")(_get_dialect_rules)
        server.tool(name="get_connection_dialect")(_get_connection_dialect)

        # Query training tools
        server.tool(name="query_status")(_query_status)
        server.tool(name="query_generate")(_query_generate)
        server.tool(name="query_approve")(_query_approve)
        server.tool(name="query_feedback")(_query_feedback)
        server.tool(name="query_add_rule")(_query_add_rule)
        server.tool(name="query_list_examples")(_query_list_examples)
        server.tool(name="query_list_rules")(_query_list_rules)

        # Advanced generation tools
        server.tool(name="get_data")(_get_data)
        server.tool(name="test_elicitation")(_test_elicitation)
        server.tool(name="test_sampling")(_test_sampling)

    return server


# Create the server instance
mcp = _create_server()


def _configure_logging():
    """Configure logging before anything else."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _configure_observability():
    """Configure Logfire observability if token is set."""
    settings = get_settings()
    if settings.logfire_token:
        import logfire

        logfire.configure(
            token=settings.logfire_token,
            service_name="db-meta-v2",
            environment=os.environ.get("ENVIRONMENT", "development"),
            # Disable scrubbing to preserve SQL queries and user input in logs
            # Default patterns would scrub 'password', 'secret', 'auth', 'session', etc.
            scrubbing=False,
        )
        # Instrument MCP server (all tool calls)
        logfire.instrument_mcp()
        # Instrument all PydanticAI agents automatically
        Agent.instrument_all()
        logging.getLogger(__name__).info("Logfire observability enabled (scrubbing disabled)")


def main():
    """Run the MCP server."""
    _configure_logging()
    _configure_observability()

    # Ensure vault directory structure exists
    ensure_vault_structure()

    # Migrate legacy provider data if present
    migrate_legacy_provider_data()

    settings = get_settings()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting db-meta-v2 in {settings.tool_mode} mode")

    if settings.mcp_transport == "http":
        mcp.run(
            transport="http",
            host=settings.mcp_host,
            port=settings.mcp_port,
            path=settings.mcp_path,
        )
    else:
        # Default: stdio for local/Claude Desktop
        mcp.run()


if __name__ == "__main__":
    main()
