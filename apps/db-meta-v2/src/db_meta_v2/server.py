"""FastMCP server for db-meta-v2."""

import logging
import os
from pathlib import Path

from fastmcp import FastMCP
from pydantic_ai import Agent
from starlette.requests import Request
from starlette.responses import JSONResponse

from db_meta_v2.config import get_settings
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
from db_meta_v2.tools.shell import _shell
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


# Create MCP server with optional auth
mcp = FastMCP(
    name="db-meta-v2",
    auth=_get_auth_provider(),
    instructions="""
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
""",
)


# =============================================================================
# MCP Resources - automatically exposed to clients
# =============================================================================


@mcp.resource("protocol://knowledge-vault")
def get_protocol() -> str:
    """Knowledge vault protocol - READ THIS FIRST before any query work.

    Contains critical instructions for:
    - Database hierarchy (catalog.schema.table)
    - How to search and save examples
    - User transparency requirements
    """
    settings = get_settings()
    protocol_path = Path(settings.vault_path) / "PROTOCOL.md"
    if protocol_path.exists():
        return protocol_path.read_text()
    return "PROTOCOL.md not found. Run vault initialization."


@mcp.resource("protocol://sql-rules")
def get_sql_rules() -> str:
    """SQL generation rules for this database.

    Contains:
    - Database hierarchy rules (2-level vs 3-level)
    - Common mistakes to avoid
    - Dialect-specific guidance
    """
    settings = get_settings()
    rules_path = Path(settings.vault_path) / "instructions" / "sql_rules.md"
    if rules_path.exists():
        return rules_path.read_text()
    return "sql_rules.md not found."


# Health check endpoint for k8s probes
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for load balancers and k8s probes."""
    settings = get_settings()
    return JSONResponse(
        {
            "status": "healthy",
            "service": "db-meta-v2",
            "provider_id": settings.provider_id,
        }
    )


async def _ping() -> dict:
    """Health check - verify server is running."""
    settings = get_settings()
    return {
        "status": "ok",
        "provider_id": settings.provider_id,
        "database_configured": bool(settings.database_url),
    }


async def _get_config() -> dict:
    """Get current server configuration (non-sensitive)."""
    settings = get_settings()
    return {
        "provider_id": settings.provider_id,
        "resources_dir": settings.resources_dir,
        "providers_dir": settings.providers_dir,
        "database_configured": bool(settings.database_url),
    }


# Register core tools
ping = mcp.tool(name="ping")(_ping)
get_config = mcp.tool(name="get_config")(_get_config)

# Register database tools
test_connection = mcp.tool(name="test_connection")(_test_connection)
detect_dialect = mcp.tool(name="detect_dialect")(_detect_dialect)
list_catalogs = mcp.tool(name="list_catalogs")(_list_catalogs)
list_schemas = mcp.tool(name="list_schemas")(_list_schemas)
list_tables = mcp.tool(name="list_tables")(_list_tables)
describe_table = mcp.tool(name="describe_table")(_describe_table)
sample_table = mcp.tool(name="sample_table")(_sample_table)

# Register dialect tools
get_dialect_rules = mcp.tool(name="get_dialect_rules")(_get_dialect_rules)
get_connection_dialect = mcp.tool(name="get_connection_dialect")(_get_connection_dialect)

# Register MCP setup tools (schema discovery wizard)
# Prefixed with mcp_setup_ to avoid confusion with business "onboarding" queries
mcp_setup_status = mcp.tool(name="mcp_setup_status")(_onboarding_status)
mcp_setup_start = mcp.tool(name="mcp_setup_start")(_onboarding_start)
mcp_setup_add_ignore_pattern = mcp.tool(name="mcp_setup_add_ignore_pattern")(
    _onboarding_add_ignore_pattern
)
mcp_setup_remove_ignore_pattern = mcp.tool(name="mcp_setup_remove_ignore_pattern")(
    _onboarding_remove_ignore_pattern
)
mcp_setup_import_ignore_patterns = mcp.tool(name="mcp_setup_import_ignore_patterns")(
    _onboarding_import_ignore_patterns
)
mcp_setup_discover = mcp.tool(name="mcp_setup_discover")(_onboarding_discover)
mcp_setup_reset = mcp.tool(name="mcp_setup_reset")(_onboarding_reset)
mcp_setup_next = mcp.tool(name="mcp_setup_next")(_onboarding_next)
mcp_setup_approve = mcp.tool(name="mcp_setup_approve")(_onboarding_approve)
mcp_setup_skip = mcp.tool(name="mcp_setup_skip")(_onboarding_skip)
mcp_setup_bulk_approve = mcp.tool(name="mcp_setup_bulk_approve")(_onboarding_bulk_approve)

# Register MCP domain tools (domain model generation)
mcp_domain_status = mcp.tool(name="mcp_domain_status")(_domain_status)
mcp_domain_generate = mcp.tool(name="mcp_domain_generate")(_domain_generate)
mcp_domain_approve = mcp.tool(name="mcp_domain_approve")(_domain_approve)
mcp_domain_skip = mcp.tool(name="mcp_domain_skip")(_domain_skip)

# Register query training tools
query_status = mcp.tool(name="query_status")(_query_status)
query_generate = mcp.tool(name="query_generate")(_query_generate)
query_approve = mcp.tool(name="query_approve")(_query_approve)
query_feedback = mcp.tool(name="query_feedback")(_query_feedback)
query_add_rule = mcp.tool(name="query_add_rule")(_query_add_rule)
query_list_examples = mcp.tool(name="query_list_examples")(_query_list_examples)
query_list_rules = mcp.tool(name="query_list_rules")(_query_list_rules)

# Register import tools (bulk import from legacy format)
import_instructions = mcp.tool(name="import_instructions")(_import_instructions)
import_examples = mcp.tool(name="import_examples")(_import_examples)

# Register SQL generation tools (main entry points)
get_data = mcp.tool(name="get_data")(_get_data)
run_sql = mcp.tool(name="run_sql")(_run_sql)
validate_sql = mcp.tool(name="validate_sql")(_validate_sql)
get_result = mcp.tool(name="get_result")(_get_result)
export_results = mcp.tool(name="export_results")(_export_results)
test_elicitation = mcp.tool(name="test_elicitation")(_test_elicitation)
test_sampling = mcp.tool(name="test_sampling")(_test_sampling)

# Register knowledge vault tool
shell = mcp.tool(name="shell")(_shell)


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
        )
        # Instrument MCP server (all tool calls)
        logfire.instrument_mcp()
        # Instrument all PydanticAI agents automatically
        Agent.instrument_all()
        logging.getLogger(__name__).info("Logfire observability enabled")


def main():
    """Run the MCP server."""
    _configure_logging()
    _configure_observability()

    # Ensure vault directory structure exists
    ensure_vault_structure()

    # Migrate legacy provider data if present
    migrate_legacy_provider_data()

    settings = get_settings()

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
