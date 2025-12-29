import asyncio
import logging.config
from typing import Any

from fastmcp import Client, FastMCP

from dbmeta_app.api.routes import mcp
from dbmeta_app.config import get_settings
from dbmeta_app.logs import LOGGING_CONFIG
from dbmeta_app.vector_db.milvus import clear_bm25_cache

logging.config.dictConfig(LOGGING_CONFIG)

settings = get_settings()

# Clear BM25 cache on module load to ensure fresh index on deploy
clear_bm25_cache()


async def check_mcp(mcp_server: FastMCP):
    # List the components that were created
    tools = await mcp_server.get_tools()
    resources = await mcp_server.get_resources()
    templates = await mcp_server.get_resource_templates()

    # client = Client(f"ws://localhost:{settings.port}")
    client = Client(mcp_server)
    async with client:
        try:
            prompts: Any = await client.call_tool(
                "prompt_items",
                {
                    "req": {
                        "user_request": "List all tables in the warehouse",
                        "db": "wh_v2",
                    }
                },
            )
            preflight: Any = await client.call_tool(
                "preflight_query",
                {
                    "req": {
                        "sql": "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' ORDER BY table_schema, table_name",
                        "db": "wh_v2",
                    }
                },
            )

        except Exception:
            pass

    return mcp_server


def main():
    """
    Console entry point for `db-meta`. Must be a sync callable.
    """
    # Optional: skip this on production boots if it slows startup; gate via env
    # if settings.check_mcp_on_start:
    asyncio.run(check_mcp(mcp))

    # Start the FastMCP (FastAPI/uvicorn) server; this is typically blocking.
    mcp.run(transport="http", host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
