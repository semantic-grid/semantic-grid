import json

from fastmcp import Client

from fm_app.api.v1.model import (
    DBType,
    FlowType,
    McpServerRequest,
    WorkerRequest,
)


def get_db_name(req: WorkerRequest):
    if (
        req.db == DBType.new_wh
        or req.flow == FlowType.openai_simple_new_wh
        or req.flow == FlowType.gemini_simple_new_wh
        or req.flow == FlowType.deepseek_simple_new_wh
        or req.flow == FlowType.anthropic_simple_new_wh
    ):
        db = "new_wh"
    elif (
        req.db == DBType.v2
        or req.flow == FlowType.openai_simple_v2
        or req.flow == FlowType.gemini_simple_v2
        or req.flow == FlowType.deepseek_simple_v2
        or req.flow == FlowType.anthropic_simple_v2
    ):
        db = "wh_v2"
    else:
        db = "wh"
    return db


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


async def get_db_meta_database_overview(
    req: McpServerRequest, flow_step_num, settings, logger
):
    """Get high-level database overview for discovery/welcome messages."""
    db = get_db_name(req)

    # Extract mode from request if present (format: "command|mode=value")
    mode = "help"  # default
    if "|mode=" in req.request:
        parts = req.request.split("|mode=")
        if len(parts) > 1:
            mode = parts[1]

    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            result = await client.call_tool(
                "get_database_overview",
                {
                    "db": db,
                    "mode": mode,
                },
            )
            overview_text = result[0].text
            print(f">>> DATABASE_OVERVIEW mode={mode} len={len(overview_text)}")
            print(f">>> OVERVIEW_PREVIEW: {overview_text[:500]}")
            logger.info(
                "Got database overview",
                flow_stage="discovery_overview",
                flow_step_num=flow_step_num,
                mode=mode,
                overview_length=len(overview_text),
            )

        except Exception as e:
            logger.error(
                "Error getting database overview",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return overview_text
