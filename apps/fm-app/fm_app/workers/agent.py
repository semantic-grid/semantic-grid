from agents import Agent, ModelSettings
from agents.mcp import MCPServerSse
from dotenv import load_dotenv

from fm_app.api.model import StructuredResponse
from fm_app.config import get_settings
from fm_app.workers.prompt_elements import (
    expertise_prefix,
    instruction_mcp,
)

load_dotenv(".env")
settings = get_settings()
_agent = None
_dbmeta_mcp = None


async def init_agent() -> (MCPServerSse, Agent[StructuredResponse]):
    global _agent, _dbmeta_mcp

    if _agent is None:

        instructions = f"""
               {expertise_prefix}\n 
               {instruction_mcp}\n
               """

        _dbmeta_mcp = MCPServerSse(
            name="ApeGPT DB Metadata MCP Server",
            # params={"url": f"{settings.dbmeta}sse"},
            params={"url": "https://api.apegpt.ai/sse"},
            cache_tools_list=True,
        )
        await _dbmeta_mcp.connect()

        _agent = Agent[StructuredResponse](
            name="ApeGPT Solana Agent",
            instructions=instructions,
            model=settings.openai_llm_name,
            model_settings=ModelSettings(temperature=0, parallel_tool_calls=True),
            mcp_servers=[_dbmeta_mcp],
            output_type=StructuredResponse,
        )

        return _dbmeta_mcp, _agent

    return _dbmeta_mcp, _agent


async def close_agent():
    global _agent, _dbmeta_mcp

    if _dbmeta_mcp is not None:
        await _dbmeta_mcp.cleanup()
        _dbmeta_mcp = None
        _agent = None
