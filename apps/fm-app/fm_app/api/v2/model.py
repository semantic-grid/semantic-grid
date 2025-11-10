"""
v2 API Models for Flexible Chat Architecture

This module defines Pydantic models for the v2 message-based API.
Designed to be compatible with OpenAI, Anthropic, and Gemini APIs.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# Import v1 models for reuse
from fm_app.api.v1.model import Column, Refs, View


class MessageRole(str, Enum):
    """Who created the message"""

    USER = "user"  # Human user input
    ASSISTANT = "assistant"  # AI/system response
    SYSTEM = "system"  # System-generated (welcome, notifications)
    TOOL = "tool"  # Tool execution results (MCP, functions)
    COMMAND = "command"  # Special commands (internal use)


class MessageKind(str, Enum):
    """What type of message this is"""

    CHAT = "chat"  # Normal conversation message
    SLASH_COMMAND = "slash_command"  # User typed /command
    TOOL_RESULT = "tool_result"  # Result from MCP/tool execution
    NOTIFICATION = "notification"  # System notification to user
    DEBUG = "debug"  # Debug/trace information
    QUERY_RESULT = "query_result"  # SQL query execution result
    CHART = "chart"  # Chart/visualization data
    TABLE = "table"  # Table data

    # Agentic flow support
    EXECUTION_PLAN = "execution_plan"  # Multi-step execution plan
    PLAN_APPROVAL = "plan_approval"  # User approval/rejection of plan
    PLAN_STEP = "plan_step"  # Individual step in execution
    CLARIFICATION = "clarification"  # Request for user input/decision
    CLARIFICATION_RESPONSE = "clarification_response"  # User's response


class MessageStatus(str, Enum):
    """Processing status of the message"""

    PENDING = "pending"  # Message created, not processed
    PROCESSING = "processing"  # Currently being processed
    COMPLETED = "completed"  # Successfully completed
    FAILED = "failed"  # Processing failed
    CANCELLED = "cancelled"  # User cancelled


class AgentEventType(str, Enum):
    """Types of agent status events during processing"""

    # Lifecycle events
    TASK_RECEIVED = "task_received"  # Worker received the task
    TASK_STARTED = "task_started"  # Worker started processing
    TASK_COMPLETED = "task_completed"  # Worker completed successfully
    TASK_FAILED = "task_failed"  # Worker failed
    TASK_CANCELLED = "task_cancelled"  # User cancelled

    # Analysis events
    INTENT_ANALYZING = "intent_analyzing"  # Analyzing user intent
    INTENT_ANALYZED = "intent_analyzed"  # Intent understood

    # Planning events
    PLAN_DRAFTING = "plan_drafting"  # Creating execution plan
    PLAN_DRAFTED = "plan_drafted"  # Plan created
    PLAN_UPDATED = "plan_updated"  # Plan modified during execution
    PLAN_STEP_STARTED = "plan_step_started"  # Starting a plan step
    PLAN_STEP_COMPLETED = "plan_step_completed"  # Completed a plan step

    # MCP/Tool events
    TOOL_CALLING = "tool_calling"  # Calling an MCP tool
    TOOL_CALLED = "tool_called"  # Tool call completed
    TOOL_FAILED = "tool_failed"  # Tool call failed

    # LLM events
    LLM_THINKING = "llm_thinking"  # Engaging LLM
    LLM_RESPONDED = "llm_responded"  # LLM response received

    # Validation events
    SQL_VALIDATING = "sql_validating"  # Validating SQL (explain_analyze)
    SQL_VALIDATED = "sql_validated"  # SQL validation passed
    SQL_INVALID = "sql_invalid"  # SQL validation failed
    SQL_REPAIRING = "sql_repairing"  # Repairing failed SQL

    # Execution events
    QUERY_EXECUTING = "query_executing"  # Executing SQL query
    QUERY_EXECUTED = "query_executed"  # Query execution completed
    QUERY_FAILED = "query_failed"  # Query execution failed

    # Data events
    DATA_PROCESSING = "data_processing"  # Processing query results
    DATA_PROCESSED = "data_processed"  # Results processed
    CHART_GENERATING = "chart_generating"  # Creating visualization
    CHART_GENERATED = "chart_generated"  # Visualization created

    # Storage events
    ARTIFACT_SAVING = "artifact_saving"  # Saving results/metadata
    ARTIFACT_SAVED = "artifact_saved"  # Artifacts persisted

    # Error recovery
    ERROR_DETECTED = "error_detected"  # Error occurred
    ERROR_RECOVERING = "error_recovering"  # Attempting recovery
    ERROR_RECOVERED = "error_recovered"  # Recovery successful

    # General progress
    PROGRESS_UPDATE = "progress_update"  # Generic progress indicator
    INFO = "info"  # Informational message
    DEBUG = "debug"  # Debug information


class AgentEventLevel(str, Enum):
    """Severity/importance level of the event"""

    DEBUG = "debug"  # Low-level debugging info
    INFO = "info"  # Normal informational events
    SUCCESS = "success"  # Successful completion events
    WARNING = "warning"  # Warnings (non-fatal issues)
    ERROR = "error"  # Errors (failures)


# Persistence rules by message kind
PERSISTENCE_RULES = {
    MessageKind.CHAT: True,
    MessageKind.SLASH_COMMAND: True,
    MessageKind.QUERY_RESULT: True,
    MessageKind.EXECUTION_PLAN: True,
    MessageKind.PLAN_APPROVAL: True,
    MessageKind.CLARIFICATION: True,
    MessageKind.CLARIFICATION_RESPONSE: True,
    MessageKind.TOOL_RESULT: True,
    MessageKind.TABLE: True,
    MessageKind.CHART: True,
    # Transient (not stored in DB)
    MessageKind.NOTIFICATION: False,
    MessageKind.PLAN_STEP: False,
    MessageKind.DEBUG: False,  # Unless debug mode enabled
}


class MessageAttachment(BaseModel):
    """Binary/large content attachment"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    message_id: str

    # Content type
    content_type: str  # MIME type (image/png, audio/mp3, etc.)

    # Storage (one of these)
    content_url: Optional[str] = None  # S3/CDN URL (preferred for large files)
    content_data: Optional[bytes] = None  # Inline binary (<1MB)

    # Metadata
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def data_uri(self) -> Optional[str]:
        """Get data URI for inline content"""
        if self.content_data:
            import base64

            b64 = base64.b64encode(self.content_data).decode()
            return f"data:{self.content_type};base64,{b64}"
        return None


class Message(BaseModel):
    """Core message model for v2 flexible chat"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str  # Links to existing sessions table

    # Core content (polymorphic - stores text, JSON, or references)
    content: Union[str, Dict[str, Any], List[Any]]
    content_type: str = "text/markdown"  # MIME type for content

    # Classification
    role: MessageRole  # Who created this message
    kind: MessageKind  # What type of message this is
    persistent: bool = True  # Whether to store in DB (False for transient messages)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Optional relationships
    parent_id: Optional[str] = None  # Reply-to relationship
    thread_id: Optional[str] = None  # Grouping messages into threads
    tags: List[str] = Field(default_factory=list)  # Flexible tagging

    # Binary/large content via attachments
    attachments: List[MessageAttachment] = Field(default_factory=list)

    # Status
    status: MessageStatus = MessageStatus.PENDING
    error: Optional[str] = None

    # Typed getters for content
    @property
    def text(self) -> Optional[str]:
        """Get content as text (for text/markdown types)"""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, dict) and "text" in self.content:
            return self.content["text"]
        return None

    @property
    def data(self) -> Optional[Dict[str, Any]]:
        """Get content as structured data (for JSON types)"""
        if isinstance(self.content, dict):
            return self.content
        return None

    @property
    def items(self) -> Optional[List[Any]]:
        """Get content as list (for array types)"""
        if isinstance(self.content, list):
            return self.content
        return None

    @property
    def binary_url(self) -> Optional[str]:
        """Get URL for binary content (images, audio, video)"""
        # Check if content is data URI
        if isinstance(self.content, str) and self.content.startswith("data:"):
            return self.content

        # Check if content has reference to attachment
        if isinstance(self.content, dict) and "attachment_id" in self.content:
            att_id = self.content["attachment_id"]
            att = next((a for a in self.attachments if a.id == att_id), None)
            return att.content_url if att else None

        # Check first attachment
        if self.attachments:
            return self.attachments[0].content_url or self.attachments[0].data_uri

        return None

    # Factory methods for common message types
    @classmethod
    def create_text(cls, text: str, **kwargs) -> "Message":
        """Create a text message"""
        return cls(content=text, content_type="text/markdown", **kwargs)

    @classmethod
    def create_chart(cls, chart_data: Dict[str, Any], **kwargs) -> "Message":
        """Create a chart message"""
        return cls(
            content=chart_data,
            content_type="application/vnd.chart+json",
            kind=MessageKind.CHART,
            **kwargs,
        )

    @classmethod
    def create_table(cls, rows: List[Dict], columns: List[str], **kwargs) -> "Message":
        """Create a table message"""
        return cls(
            content={"columns": columns, "rows": rows},
            content_type="application/vnd.table+json",
            kind=MessageKind.TABLE,
            **kwargs,
        )

    @classmethod
    def create_image(
        cls,
        image_url: str = None,
        image_data: bytes = None,
        alt_text: str = "",
        **kwargs,
    ) -> "Message":
        """Create an image message"""
        if image_data and len(image_data) < 100_000:  # <100KB: use data URI
            import base64

            b64 = base64.b64encode(image_data).decode()
            return cls(
                content=f"data:image/png;base64,{b64}",
                content_type="image/png",
                **kwargs,
            )
        else:  # Large files: use attachment
            attachment = MessageAttachment(
                content_type="image/png",
                content_url=image_url,
                content_data=image_data
                if image_data and len(image_data) < 1_000_000
                else None,
                metadata={"alt_text": alt_text},
            )
            return cls(
                content={"attachment_id": attachment.id, "alt_text": alt_text},
                content_type="image/png",
                attachments=[attachment],
                **kwargs,
            )

    @classmethod
    def create_notification(cls, text: str, **kwargs) -> "Message":
        """Create a transient notification message"""
        return cls(
            content=text,
            content_type="text/plain",
            kind=MessageKind.NOTIFICATION,
            persistent=False,  # Not stored in DB
            **kwargs,
        )

    @classmethod
    def create_plan_step_update(cls, plan_id: str, step_id: str, **kwargs) -> "Message":
        """Create a transient step progress update"""
        return cls(
            content={"plan_id": plan_id, "step_id": step_id, "status": "running"},
            kind=MessageKind.PLAN_STEP,
            persistent=False,  # Not stored, just streamed via SSE
            **kwargs,
        )


class MessageQuery(BaseModel):
    """v2 query model - wraps v1 concepts"""

    id: UUID = Field(default_factory=uuid4)
    message_id: UUID
    sql_query: str
    row_count: Optional[int] = None
    execution_time_ms: Optional[int] = None

    # v1 lineage fields
    prompt_hash: Optional[str] = None
    mcp_call_hash: Optional[str] = None
    profile: Optional[str] = None

    # Link to v1 query if needed
    v1_query_id: Optional[UUID] = None

    # v1 QueryMetadata stored here
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # metadata can contain: {
    #   "summary": "...",
    #   "columns": [...],  # List of Column objects
    #   "query_follow_ups": [...],
    #   "explanation": {...},
    #   etc.
    # }
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentEvent(BaseModel):
    """
    Real-time status event emitted during agent processing.

    These events stream to clients via SSE to show agent progress.
    Transient (not persisted to DB) - for UI feedback only.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID  # Links to session
    message_id: Optional[str] = None  # Links to message being processed (if applicable)

    # Event classification
    event_type: AgentEventType
    level: AgentEventLevel = AgentEventLevel.INFO

    # Event content
    message: str  # Human-readable status message
    details: Dict[str, Any] = Field(default_factory=dict)  # Additional context

    # Progress tracking
    step: Optional[int] = None  # Current step number (if multi-step)
    total_steps: Optional[int] = None  # Total steps (if known)
    progress_percent: Optional[float] = None  # 0-100 progress indicator

    # Timing
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: Optional[int] = None  # Duration of this event (for completed events)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        session_id: UUID,
        event_type: AgentEventType,
        message: str,
        level: AgentEventLevel = AgentEventLevel.INFO,
        message_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        step: Optional[int] = None,
        total_steps: Optional[int] = None,
        progress_percent: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AgentEvent":
        """Convenience factory for creating events"""
        return cls(
            session_id=session_id,
            message_id=message_id,
            event_type=event_type,
            level=level,
            message=message,
            details=details or {},
            step=step,
            total_steps=total_steps,
            progress_percent=progress_percent,
            metadata=metadata or {},
        )

    def to_sse_dict(self) -> Dict[str, Any]:
        """Convert to SSE event data format"""
        return {
            "id": self.id,
            "session_id": str(self.session_id),
            "message_id": self.message_id,
            "event_type": self.event_type.value,
            "level": self.level.value,
            "message": self.message,
            "details": self.details,
            "step": self.step,
            "total_steps": self.total_steps,
            "progress_percent": self.progress_percent,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


# API Request/Response Models


class CreateSessionRequest(BaseModel):
    """Request to create a new v2 session"""

    name: Optional[str] = None
    tags: Optional[str] = None
    parent: Optional[UUID] = None


class CreateSessionResponse(BaseModel):
    """Response from creating a new v2 session"""

    session_id: UUID
    api_version: str = "v2"
    created_at: datetime
    messages: List[Message] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    """Request to send a message to a session"""

    role: MessageRole
    kind: MessageKind
    content: Union[str, Dict[str, Any], List[Any]]
    content_type: str = "text/markdown"
    parent_id: Optional[str] = None
    thread_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SendMessageResponse(BaseModel):
    """Response from sending a message"""

    message_id: str
    status: MessageStatus
    assistant_messages: List[Message] = Field(default_factory=list)


class GetSessionResponse(BaseModel):
    """Response from getting a session"""

    session_id: UUID
    api_version: str
    created_at: datetime
    messages: List[Message]
    message_count: int


class GetMessagesResponse(BaseModel):
    """Response from listing messages"""

    messages: List[Message]
    total_count: int
    has_more: bool
