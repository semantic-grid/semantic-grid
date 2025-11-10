"""
MCP Flow - Agent-based SQL generation with dual MCP server integration.

This flow uses the Anthropic Agents framework to orchestrate SQL generation
through direct MCP server interactions:

1. **Prompt Assembly**: Builds instructions from multiple sources
   - Expertise prefix (domain knowledge)
   - DB-ref prompts (reference data, examples)
   - MCP-specific instructions
   - Model-specific instructions
   - ClickHouse-specific SQL guidance

2. **Dual MCP Server Setup**:
   - DB Meta MCP Server (SSE): Provides schema metadata, validation tools
   - Solana DB MCP Server (FastMCP): Executes queries via fetch_data tool

3. **Agent Execution**: Uses Anthropic's Agent with structured output
   - Agent name: "ApeGPT Solana Agent"
   - Output type: StructuredResponse (includes SQL, CSV, metadata)
   - Settings: Temperature=0, parallel_tool_calls=True
   - MCP servers: db_meta_mcp for schema/validation

4. **SQL Generation**: Agent generates SQL using MCP tools for schema context
   - Calls MCP resources/functions with db_name parameter
   - Leverages parallel tool calls for efficiency
   - Returns structured response with SQL

5. **Query Execution**: Executes SQL via solana_db.py MCP server
   - Uses FastMCP Client to call fetch_data tool
   - Passes SQL, db, and settings to the tool
   - Retrieves CSV results from tool response

6. **Error Handling**: Comprehensive error handling for MCP client operations
   - ClientError: Tool call failures
   - ConnectionError: MCP server connection issues
   - General exceptions: Unexpected errors

Key features:
- Agent-based orchestration vs direct LLM calls
- Dual MCP server architecture (SSE + FastMCP)
- Structured output with type validation
- Parallel tool calling for performance
- Direct MCP tool execution for queries

Differences from other flows:
- Uses Anthropic Agents framework vs raw LLM API
- MCP servers are first-class citizens (agent-integrated)
- No retry loop (agent handles tool interactions)
- No query storage or lineage tracking
- Focused on demonstration of MCP integration patterns

Use cases:
- Demonstrating MCP server integration patterns
- Agent-based query workflows
- Scenarios requiring multiple MCP servers in coordination
- Prototyping agentic SQL generation approaches
"""

import datetime
import json
from typing import Type

import structlog
from agents import Agent, ModelSettings, Runner
from agents.mcp import MCPServerSse
from celery.utils.log import get_task_logger
from dotenv import load_dotenv
from fastmcp.client import Client
from fastmcp.client.logging import LogMessage
from fastmcp.exceptions import ClientError
from mcp.types import TextContent

from fm_app.ai_models.model import AIModel
from fm_app.api.v1.model import RequestStatus, StructuredResponse, WorkerRequest
from fm_app.config import get_settings
from fm_app.mcp_servers.db_meta import get_db_name
from fm_app.mcp_servers.db_ref import get_db_ref_prompt_items
from fm_app.workers.experimental.prompt_elements import (
    expertise_prefix,
    instruction_clickhouse,
    instruction_mcp,
)

server_script = "fm_app/mcp_servers/solana_db.py"  # Path to a Python server file

load_dotenv(".env")
settings = get_settings()
logger = structlog.wrap_logger(get_task_logger(__name__))


def log_handler(params: LogMessage):
    logger.info(
        f"[MCP - {params.level.upper()}] {params.logger or 'default'}: {params.data}"
    )


db_client = Client(server_script, log_handler=log_handler)
print(db_client.transport)


async def mcp_flow(req: WorkerRequest, ai_model: Type[AIModel]):
    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_mcp"
    )

    logger.info("Starting flow", flow_stage="start", flow_step_num=0, flow=req.flow)

    req.structured_response = StructuredResponse()
    ts = datetime.datetime.now()
    print("\n\nSTART:", req.request, "\n\n")

    # await get_db_meta_mcp_prompt_items(req, 0, settings, logger)
    dbref_prompts = get_db_ref_prompt_items(req, 0, settings, logger)
    db_name = get_db_name(req)

    ts1 = datetime.datetime.now()
    print("\n\nDBREF:", ts1 - ts, "\n\n")

    instructions = f"""
       {expertise_prefix}\n
       {dbref_prompts}\n
       {instruction_mcp}\n
       When calling MCP resources or functions that requre **db_name** param,
       use db_name="{db_name}"\n
       {ai_model.get_specific_instructions()}\n
       {instruction_clickhouse}
       """

    async with MCPServerSse(
        name="DB Metadata Services",
        params={"url": f"{settings.dbmeta}sse"},
    ) as db_meta_mcp:
        agent = Agent[StructuredResponse](
            name="ApeGPT Solana Agent",
            instructions=instructions,
            model=settings.openai_llm_name,
            model_settings=ModelSettings(temperature=0, parallel_tool_calls=True),
            mcp_servers=[db_meta_mcp],
            output_type=StructuredResponse,
        )

        sql_res = await Runner.run(starting_agent=agent, input=req.request)
        ts2 = datetime.datetime.now()
        print("\n\nSQL:", ts2 - ts1, "\n\n")

        if sql_res.final_output is None or sql_res.final_output.sql is None:
            req.status = RequestStatus.error
            req.err = "No SQL generated"
            return req

        req.structured_response.sql = sql_res.final_output.sql

        async with db_client:
            # print(f"DB client connected: {db_client.is_connected()}")

            try:
                result: list[TextContent] = await db_client.call_tool(
                    "fetch_data",
                    {
                        "request": req.structured_response.sql,
                        "db": req.db,
                        "settings": settings,
                    },
                )
                data = json.loads(result[0].text)
                ts3 = datetime.datetime.now()
                print("\n\nDATA:", ts3 - ts2, "\n\n")
                if "error" in data:
                    req.status = RequestStatus.error
                    req.err = data["error"]
                    return req

                req.structured_response.csv = data["csv"]

            except ClientError as e:
                print(f"Tool call failed: {e}")
                req.status = RequestStatus.error
                req.err = str(e)
                return req
            except ConnectionError as e:
                print(f"Connection failed: {e}")
                req.status = RequestStatus.error
                req.err = str(e)
                return req
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                req.status = RequestStatus.error
                req.err = str(e)
                return req

    return req
