import json

from fastmcp import Client

from fm_app.api.model import (
    DBType,
    FlowType,
    WorkerRequest,
    McpServerRequest,
)


def get_db_name(req: McpServerRequest):
    return "wh"


async def get_db_meta_mcp_prompt_items(
    req: McpServerRequest, flow_step_num, settings, logger
):
    db = get_db_name(req)
    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            prompts = await client.call_tool(
                "prompt_items",
                {
                    "req": {
                        "user_request": req.request,
                        "db": db,
                    }
                },
            )
            # print("prompts", prompts[0].text)
            print("prompts", db, bool(prompts[0].text))

        except Exception as e:
            logger.error(
                "Error reading MCP resource",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return prompts[0].text


async def db_meta_mcp_analyze_query(
    req: McpServerRequest, sql: str, flow_step_num, settings, logger
):
    db = get_db_name(req)
    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            prompts = await client.call_tool(
                "preflight_query",
                {
                    "req": {
                        "sql": sql,
                        "db": db,
                    }
                },
            )
            print("preflight", db, bool(prompts[0].text))

        except Exception as e:
            logger.error(
                "Error reading MCP resource",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return json.loads(prompts[0].text)
