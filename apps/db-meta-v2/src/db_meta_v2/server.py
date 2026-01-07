"""FastMCP server for db-meta-v2."""

import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse


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

# Create MCP server
mcp = FastMCP(
    name="db-meta-v2",
    instructions="""
    Database metadata and query intelligence server.

    This server provides tools for:
    - Database onboarding and configuration
    - Schema introspection and description
    - SQL generation from natural language
    - Query validation and execution
    """,
)


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
ping = mcp.tool()(_ping)
get_config = mcp.tool()(_get_config)

# Register database tools
test_connection = mcp.tool()(_test_connection)
detect_dialect = mcp.tool()(_detect_dialect)
list_catalogs = mcp.tool()(_list_catalogs)
list_schemas = mcp.tool()(_list_schemas)
list_tables = mcp.tool()(_list_tables)
describe_table = mcp.tool()(_describe_table)
sample_table = mcp.tool()(_sample_table)

# Register dialect tools
get_dialect_rules = mcp.tool()(_get_dialect_rules)
get_connection_dialect = mcp.tool()(_get_connection_dialect)

# Register onboarding tools
onboarding_status = mcp.tool()(_onboarding_status)
onboarding_start = mcp.tool()(_onboarding_start)
onboarding_add_ignore_pattern = mcp.tool()(_onboarding_add_ignore_pattern)
onboarding_remove_ignore_pattern = mcp.tool()(_onboarding_remove_ignore_pattern)
onboarding_import_ignore_patterns = mcp.tool()(_onboarding_import_ignore_patterns)
onboarding_discover = mcp.tool()(_onboarding_discover)
onboarding_reset = mcp.tool()(_onboarding_reset)
onboarding_next = mcp.tool()(_onboarding_next)
onboarding_approve = mcp.tool()(_onboarding_approve)
onboarding_skip = mcp.tool()(_onboarding_skip)
onboarding_bulk_approve = mcp.tool()(_onboarding_bulk_approve)

# Register domain tools
domain_status = mcp.tool()(_domain_status)
domain_generate = mcp.tool()(_domain_generate)
domain_approve = mcp.tool()(_domain_approve)
domain_skip = mcp.tool()(_domain_skip)

# Register query training tools
query_status = mcp.tool()(_query_status)
query_generate = mcp.tool()(_query_generate)
query_approve = mcp.tool()(_query_approve)
query_feedback = mcp.tool()(_query_feedback)
query_add_rule = mcp.tool()(_query_add_rule)
query_list_examples = mcp.tool()(_query_list_examples)
query_list_rules = mcp.tool()(_query_list_rules)

# Register import tools (bulk import from legacy format)
import_instructions = mcp.tool()(_import_instructions)
import_examples = mcp.tool()(_import_examples)

# Register SQL generation tools (main entry points)
get_data = mcp.tool()(_get_data)
run_sql = mcp.tool()(_run_sql)
validate_sql = mcp.tool()(_validate_sql)
get_result = mcp.tool()(_get_result)
test_elicitation = mcp.tool()(_test_elicitation)
test_sampling = mcp.tool()(_test_sampling)


def main():
    """Run the MCP server."""
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
