"""
V2 Worker Models - Message-based processing architecture.

Unlike v1 which processes requests end-to-end, v2 workers:
- Process individual messages
- Emit multiple response messages
- Support progressive streaming
- Handle complex message kinds (slash commands, plans, etc.)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from fm_app.api.v1.model import DBType, ModelType
from fm_app.api.v2.model import Message, MessageAttachment, MessageKind, MessageQuery


class FlowTypeV2(str, Enum):
    """
    V2 Flow Types - Message-oriented processing strategies.

    Unlike v1 flows which are task-specific (simple, multistep),
    v2 flows define HOW messages are processed:
    """

    # Core flows
    DIRECT = "direct"  # Single LLM call, immediate response
    ITERATIVE = "iterative"  # Multi-turn with refinement loops
    AGENTIC = "agentic"  # Plan → Approve → Execute pattern
    STREAMING = "streaming"  # Progressive message emission

    # Specialized flows
    SLASH_COMMAND = "slash_command"  # Command interpretation and execution
    QUERY_BUILDER = "query_builder"  # SQL generation with validation
    DATA_ANALYSIS = "data_analysis"  # Query + analysis + visualization
    DISCOVERY = "discovery"  # Schema exploration and suggestions

    # Hybrid flows (combine multiple strategies)
    INTERACTIVE = "interactive"  # Intent-based routing to specialized handlers
    CONVERSATIONAL = "conversational"  # Multi-turn dialogue with context


class MessageProcessingStrategy(str, Enum):
    """
    How to handle incoming messages.
    Determines which handlers and flows to invoke.
    """

    # By content analysis
    INTENT_BASED = "intent_based"  # Analyze intent, route to handler
    PATTERN_MATCH = "pattern_match"  # Regex/pattern matching (for slash commands)

    # By message kind
    KIND_DISPATCH = "kind_dispatch"  # Route based on MessageKind

    # Hybrid
    SMART_ROUTING = "smart_routing"  # Combine intent + kind + context


class WorkerMessageRequest(BaseModel):
    """
    V2 Worker Request - processes a single user message.

    Unlike v1 WorkerRequest which contains the full request lifecycle,
    v2 focuses on a single message and emits multiple response messages.
    """

    # Message identity
    session_id: str  # String for serialization through Celery
    message_id: str  # The user message being processed
    user: str

    # Message content
    content: Union[str, Dict[str, Any], List[Any]]
    content_type: str = "text/markdown"
    kind: MessageKind

    # Processing configuration
    flow: FlowTypeV2  # Which v2 flow to use
    strategy: MessageProcessingStrategy = MessageProcessingStrategy.SMART_ROUTING
    model: ModelType
    db: DBType

    # Context
    parent_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Session history (for context-aware processing)
    recent_messages: List[Message] = Field(default_factory=list)


class WorkerMessageResponse(BaseModel):
    """
    V2 Worker Response - emits one or more assistant messages.

    Unlike v1 which updates a single request with structured response,
    v2 creates multiple messages, queries, and attachments.
    """

    # Messages emitted (can be multiple!)
    messages: List[Message] = Field(default_factory=list)

    # Associated queries (linked to messages)
    queries: List[MessageQuery] = Field(default_factory=list)

    # Attachments (charts, images, files)
    attachments: List[MessageAttachment] = Field(default_factory=list)

    # Processing metadata
    processing_time_ms: Optional[int] = None
    tokens_used: Optional[int] = None

    # Status
    success: bool = True
    error: Optional[str] = None


class MessageHandlerResult(BaseModel):
    """
    Result from a message handler (intermediate processing step).

    Handlers can emit partial results that get combined into final response.
    """

    # Content for message
    content: Union[str, Dict[str, Any], List[Any]]
    content_type: str = "text/markdown"
    kind: MessageKind

    # Optional query if SQL was generated
    sql_query: Optional[str] = None
    query_metadata: Optional[Dict[str, Any]] = None

    # Optional attachment
    attachment_data: Optional[bytes] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    persistent: bool = True  # Should this be saved to DB?


class AgenticPlan(BaseModel):
    """
    Multi-step execution plan for agentic flows.

    Used by FlowTypeV2.AGENTIC to decompose complex requests into steps.
    """

    plan_id: str
    description: str
    steps: List["AgenticStep"]
    requires_approval: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgenticStep(BaseModel):
    """Individual step in an agentic plan."""

    step_id: str
    description: str
    action: str  # query, analyze, visualize, etc.
    parameters: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)  # step_ids this depends on
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Dict[str, Any]] = None


class SlashCommand(BaseModel):
    """
    Parsed slash command from user input.

    Example: "/help query syntax" → command="help", args=["query", "syntax"]
    """

    command: str  # The command name (without /)
    args: List[str] = Field(default_factory=list)
    raw_input: str  # Original input
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QueryValidationResult(BaseModel):
    """
    Result of SQL validation (EXPLAIN, cost estimation, etc.)
    """

    is_valid: bool
    sql_query: str
    estimated_cost: Optional[float] = None
    estimated_rows: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    explain_plan: Optional[Dict[str, Any]] = None


# Forward references
AgenticPlan.model_rebuild()
