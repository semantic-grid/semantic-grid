"""
V2 Agent Worker - Agentic message-based processing using Anthropic Agents SDK.

Instead of rigid flows, uses a flexible agent that:
- Determines its own execution path
- Calls MCP tools as needed
- Emits multiple message types
- Handles multi-turn conversations naturally
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from agents import Agent, ModelSettings, Runner
from agents.mcp import MCPServerSse

from fm_app.api.v2.model import (
    Message,
    MessageKind,
    MessageQuery,
    MessageRole,
    MessageStatus,
)
from fm_app.config import Settings, get_settings
from fm_app.db.db_v2 import (
    create_message,
    create_message_query,
    get_messages_for_session,
    update_message_status,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.workers.v2.event_bus import EventEmitter
from fm_app.workers.v2.model import (
    MessageHandlerResult,
    WorkerMessageRequest,
    WorkerMessageResponse,
)

logger = structlog.wrap_logger(logging.getLogger(__name__))


class V2AgentWorker:
    """
    V2 Worker using Anthropic Agents SDK.

    Key differences from v1:
    - No rigid flow types
    - Agent determines execution path
    - Emits multiple messages per request
    - Uses prompt packs for instructions
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.agent: Optional[Agent] = None
        self.mcp_servers: List[MCPServerSse] = []
        self.initialized = False
        self._last_query_metadata: Optional[Dict[str, Any]] = None

    async def initialize(
        self, client: str = "apegpt", env: str = "prod", profile: str = "wh_v2"
    ):
        """
        Initialize the agent with MCP servers and instructions from prompt packs.

        Args:
            client: Client name for prompt pack overlays (default: apegpt)
            env: Environment (dev, staging, prod)
            profile: Database profile (wh, wh_new, wh_v2)
        """
        if self.initialized:
            logger.info("Agent already initialized")
            return

        logger.info("Initializing v2 agent", client=client, env=env, profile=profile)

        try:
            # Load instructions from prompt packs
            instructions = await self._load_instructions(client, env, profile)

            # Initialize MCP servers
            await self._init_mcp_servers()

            # Create agent
            self.agent = Agent[dict](
                name="Semantic Grid Assistant",
                instructions=instructions,
                model=self.settings.openai_llm_name,
                model_settings=ModelSettings(
                    temperature=0, parallel_tool_calls=True, max_tokens=4096
                ),
                mcp_servers=self.mcp_servers,
            )

            self.initialized = True
            logger.info("Agent initialized successfully")

        except Exception as e:
            logger.error("Failed to initialize agent", error=str(e), exc_info=True)
            raise

    async def _load_instructions(self, client: str, env: str, profile: str) -> str:
        """Load agent instructions from prompt packs."""
        try:
            # Use PromptAssembler to load and render the prompt with client overlays
            assembler = PromptAssembler(
                repo_root=self.settings.packs_resources_dir,
                component="fm_app",
                client=client,
                env=env,
                system_version="v2.0.0",  # Use V2 system pack
            )

            # Create request context for MCP
            from fm_app.prompt_assembler.prompt_packs import RequestContext

            req_ctx = RequestContext(
                request_id="agent_init",
                profile=profile,
            )

            # Render the agent_v2 slot
            slot_material = await assembler.render_async(
                slot="agent_v2",
                variables={
                    "profile": profile,
                    "client": client,
                    "env": env,
                },
                req_ctx=req_ctx,
                mcp_caps=None,  # V2 doesn't pre-fetch MCP resources
            )

            instructions = slot_material.prompt
            logger.info(
                "Loaded agent instructions from prompt pack",
                client=client,
                env=env,
                slot="agent_v2",
                instruction_length=len(instructions),
                lineage=slot_material.lineage,
            )
            return instructions

        except Exception as e:
            logger.error(
                "Failed to load instructions from prompt pack",
                error=str(e),
                exc_info=True,
            )
            # Fallback to basic instructions
            return self._get_fallback_instructions()

    def _get_fallback_instructions(self) -> str:
        """Fallback instructions if prompt pack loading fails."""
        return """
You are an expert data analysis assistant for blockchain and cryptocurrency data.
You MUST use the available MCP tools to answer user questions about data.

## Critical Rules
1. For ANY question about data, tables, queries, or database content - USE THE MCP TOOLS
2. ALWAYS start by calling get_prompt_bundle to understand the schema
3. For queries like "list tables", "show data", "count trades" - USE execute_query tool
4. Never just respond with text - actually query the database using the tools

## Available MCP Tools (YOU MUST USE THESE)
- get_prompt_bundle: Get schema information and available tables
- execute_query: Execute SQL queries against the database
- explain_analyze: Validate SQL before execution

## Example Workflow
User: "list all tables in the database"
YOU MUST:
1. Call get_prompt_bundle to get schema info
2. Call execute_query with SQL to show tables
3. Return the actual results

User: "show me the count of trades"
YOU MUST:
1. Call get_prompt_bundle to find the trades table
2. Call execute_query with "SELECT COUNT(*) FROM trades LIMIT 100"
3. Return the actual count

## Response Format
Return a simple text response with the query results. The system will handle formatting.
"""

    async def _init_mcp_servers(self):
        """Initialize MCP servers based on configuration."""
        try:
            # DB Metadata MCP Server
            dbmeta_mcp = MCPServerSse(
                name="Database Metadata",
                params={"url": f"{self.settings.dbmeta}sse"},
                cache_tools_list=True,
            )
            await dbmeta_mcp.connect()
            self.mcp_servers.append(dbmeta_mcp)
            logger.info("Connected to dbmeta MCP server")

            # DB Reference MCP Server
            try:
                dbref_mcp = MCPServerSse(
                    name="Database Reference",
                    params={"url": f"{self.settings.dbref}sse"},
                    cache_tools_list=True,
                )
                await dbref_mcp.connect()
                self.mcp_servers.append(dbref_mcp)
                logger.info("Connected to dbref MCP server")
            except Exception as e:
                logger.warning("Failed to connect to dbref MCP server", error=str(e))
                # dbref is optional, continue without it

        except Exception as e:
            logger.error("Failed to initialize MCP servers", error=str(e))
            raise

    async def cleanup(self):
        """Cleanup MCP connections."""
        for mcp in self.mcp_servers:
            try:
                await mcp.cleanup()
            except Exception as e:
                logger.warning("Error cleaning up MCP server", error=str(e))

        self.mcp_servers = []
        self.agent = None
        self.initialized = False
        logger.info("Agent cleanup complete")

    async def process_message(
        self, request: WorkerMessageRequest, db
    ) -> WorkerMessageResponse:
        """
        Process a user message and emit assistant response messages.

        Args:
            request: The user message request
            db: Database session

        Returns:
            WorkerMessageResponse with messages to be saved
        """
        if not self.initialized:
            await self.initialize()

        # Create event emitter for real-time status updates
        emitter = EventEmitter(
            session_id=request.session_id, message_id=request.message_id
        )

        # Set expected steps (approximate)
        emitter.set_total_steps(6)  # Start, Intent, Plan, Think, Execute, Save

        logger.info(
            "Processing message",
            session_id=str(request.session_id),
            message_id=request.message_id,
            kind=request.kind.value,
        )

        try:
            # Emit task received (non-verbal, for logging)
            await emitter.task_received()

            # Emit task started
            await emitter.task_started()

            # Analyze intent (if this is a user query)
            if request.kind == MessageKind.CHAT:
                await emitter.intent_analyzing()
                # Extract basic intent from message
                user_msg = self._format_user_message(request)
                intent = self._extract_intent(user_msg)
                await emitter.intent_analyzed(intent)

            # Build context from recent messages
            await emitter.llm_thinking("Building context from conversation history")
            context = await self._build_context(request, db)

            # Run agent
            await emitter.llm_thinking(
                "Analyzing your request and formulating response"
            )
            result = await Runner.run(
                self.agent, self._format_user_message(request), context=context
            )

            # Debug: Log what the agent returned
            logger.info(
                "Agent execution complete",
                result_type=type(result).__name__,
                final_output=str(result.final_output)[:200]
                if hasattr(result, "final_output")
                else None,
                raw_responses_count=len(result.raw_responses)
                if hasattr(result, "raw_responses")
                else 0,
                new_items_count=len(result.new_items)
                if hasattr(result, "new_items")
                else 0,
            )

            # Log raw_responses details
            if hasattr(result, "raw_responses") and result.raw_responses:
                for idx, response in enumerate(result.raw_responses):
                    logger.info(
                        f"Raw response {idx}",
                        response_type=type(response).__name__,
                        has_tool_calls=hasattr(response, "tool_calls"),
                    )

            await emitter.llm_responded()

            # Parse agent output into messages
            messages = await self._parse_agent_output(result, request)

            # Save messages to database
            await emitter.artifact_saving()

            saved_messages = []
            saved_queries = []

            for msg in messages:
                if msg.persistent:
                    saved_msg = await create_message(
                        session_id=request.session_id,
                        user_owner=request.user,
                        msg_request=msg,
                        db=db,
                    )
                    await update_message_status(
                        message_id=saved_msg.id,
                        status=MessageStatus.COMPLETED,
                        error=None,
                        db=db,
                    )
                    saved_messages.append(saved_msg)

            # If we extracted query_metadata, save it as a MessageQuery
            if self._last_query_metadata and saved_messages:
                try:
                    message_query = MessageQuery(
                        message_id=UUID(saved_messages[0].id),
                        sql_query=self._last_query_metadata.get("sql", ""),
                        metadata=self._last_query_metadata,
                        profile=request.db.value,
                    )
                    saved_query = await create_message_query(message_query, db)
                    saved_queries.append(saved_query)
                    logger.info(
                        "Saved query metadata",
                        message_id=saved_messages[0].id,
                        has_sql=bool(self._last_query_metadata.get("sql")),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to save query metadata", error=str(e), exc_info=True
                    )
                finally:
                    # Clear the metadata for next request
                    self._last_query_metadata = None

            await emitter.artifact_saved()

            logger.info(
                "Message processed successfully",
                message_count=len(saved_messages),
                query_count=len(saved_queries),
            )

            # Emit task completed
            await emitter.task_completed()

            return WorkerMessageResponse(
                messages=saved_messages, queries=saved_queries, success=True
            )

        except Exception as e:
            logger.error("Error processing message", error=str(e), exc_info=True)

            # Emit task failed event
            await emitter.task_failed(str(e))

            # Create error message
            error_msg = Message.create_text(
                text=f"I encountered an error: {str(e)}. Please try rephrasing your request.",
                session_id=request.session_id,
                role=MessageRole.ASSISTANT,
                kind=MessageKind.CHAT,
                status=MessageStatus.FAILED,
            )

            return WorkerMessageResponse(
                messages=[error_msg], success=False, error=str(e)
            )

    def _format_user_message(self, request: WorkerMessageRequest) -> str:
        """Format user message for agent."""
        if isinstance(request.content, str):
            return request.content
        elif isinstance(request.content, dict):
            return request.content.get("text", str(request.content))
        else:
            return str(request.content)

    def _extract_intent(self, message: str) -> str:
        """
        Extract a simple intent description from user message.

        This is a basic implementation - just returns a truncated version.
        In production, might use a quick LLM call for better intent extraction.
        """
        # Truncate long messages
        max_len = 100
        if len(message) > max_len:
            return message[:max_len] + "..."
        return message

    async def _build_context(self, request: WorkerMessageRequest, db) -> Dict[str, Any]:
        """
        Build context for agent from conversation history.

        Includes:
        - Recent messages (last 10)
        - Session metadata
        - Database profile
        """
        context = {
            "session_id": str(request.session_id),
            "user_id": request.user,
            "database_profile": request.db.value,
        }

        # Get recent messages for context
        try:
            recent_msgs = await get_messages_for_session(
                session_id=request.session_id,
                db=db,
                limit=10,
                offset=0,
                persistent_only=True,
            )

            context["conversation_history"] = [
                {
                    "role": msg.role.value,
                    "content": msg.text or msg.content,
                    "kind": msg.kind.value,
                }
                for msg in recent_msgs.messages
            ]
        except Exception as e:
            logger.warning("Failed to load conversation history", error=str(e))
            context["conversation_history"] = []

        return context

    async def _parse_agent_output(
        self, result, request: WorkerMessageRequest
    ) -> List[Message]:
        """
        Parse agent output into v2 Message objects.

        The agent may return:
        - Simple text → single chat message
        - Structured response with query_metadata → chat + query messages
        - Tool results → query_result messages
        """
        import json
        import re

        messages = []

        # Extract main response text
        response_text = None
        if hasattr(result, "content") and result.content:
            response_text = result.content
        elif isinstance(result, dict) and "text" in result:
            response_text = result["text"]
        elif isinstance(result, str):
            response_text = result

        # Try to extract query_metadata from response
        query_metadata = None
        if response_text:
            query_metadata = self._extract_query_metadata(response_text)

        # Create main chat message if we have text
        if response_text:
            messages.append(
                Message.create_text(
                    text=response_text,
                    session_id=request.session_id,
                    role=MessageRole.ASSISTANT,
                    kind=MessageKind.CHAT,
                    metadata={"has_query_metadata": query_metadata is not None},
                )
            )

        # If we extracted query_metadata, create a MessageQuery object
        # This will be handled separately in process_message
        if query_metadata:
            self._last_query_metadata = query_metadata

        return (
            messages
            if messages
            else [
                Message.create_text(
                    text="I processed your request but didn't generate a specific response.",
                    session_id=request.session_id,
                    role=MessageRole.ASSISTANT,
                    kind=MessageKind.CHAT,
                )
            ]
        )

    def _extract_query_metadata(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract query_metadata JSON from agent response.

        Looks for patterns like:
        - ```json { "query_metadata": {...} } ```
        - { "query_metadata": {...} }
        """
        import json
        import re

        # Try to find JSON code blocks
        json_blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
        for block in json_blocks:
            try:
                data = json.loads(block)
                if "query_metadata" in data:
                    return data["query_metadata"]
            except json.JSONDecodeError:
                continue

        # Try to find raw JSON objects
        json_objects = re.findall(
            r"\{[^{}]*\"query_metadata\"[^{}]*\{.*?\}\s*\}", text, re.DOTALL
        )
        for obj_str in json_objects:
            try:
                data = json.loads(obj_str)
                if "query_metadata" in data:
                    return data["query_metadata"]
            except json.JSONDecodeError:
                continue

        return None


# Global worker instance (initialized per worker process)
_worker_instance: Optional[V2AgentWorker] = None


async def get_worker() -> V2AgentWorker:
    """Get or create the global worker instance."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = V2AgentWorker()
        await _worker_instance.initialize()
    return _worker_instance


async def cleanup_worker():
    """Cleanup the global worker instance."""
    global _worker_instance
    if _worker_instance is not None:
        await _worker_instance.cleanup()
        _worker_instance = None
