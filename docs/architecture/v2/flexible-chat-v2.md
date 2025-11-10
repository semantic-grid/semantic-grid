# Flexible Chat Architecture (v2)

**Status**: Draft  
**Branch**: `feature/flexible-chat`  
**Created**: 2025-01-08

## Overview

This document describes the architectural transition from the current request-response paradigm (v1) to a flexible message-based system (v2). The new architecture enables:

- Slash-style commands (`/new`, `/help`, etc.) and their responses
- Multiple responses for a single request (streaming, progressive refinement)
- Multimodal requests and responses (text, images, charts, tables)
- System-initiated messages (welcome messages, notifications, debug info)

## Core Principles

1. **Flat Message Structure**: Messages stored in a flat structure in the database with optional metadata for grouping/linking
2. **Role + Kind Taxonomy**: Each message has both a `role` (who) and `kind` (what type)
3. **Frontend-Driven Grouping**: UI organization (threads, sections, etc.) handled by frontend using message metadata
4. **Backwards Compatibility**: v1 and v2 APIs coexist; existing InteractiveFlow continues to work unchanged
5. **Progressive Migration**: v2 introduces new tables/endpoints without modifying v1 schema

## Message Schema

### Core Message Model

```python
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
        if isinstance(self.content, dict) and 'text' in self.content:
            return self.content['text']
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
        return cls(
            content=text,
            content_type="text/markdown",
            **kwargs
        )
    
    @classmethod
    def create_chart(cls, chart_data: Dict[str, Any], **kwargs) -> "Message":
        """Create a chart message"""
        return cls(
            content=chart_data,
            content_type="application/vnd.chart+json",
            kind=MessageKind.CHART,
            **kwargs
        )
    
    @classmethod
    def create_table(cls, rows: List[Dict], columns: List[str], **kwargs) -> "Message":
        """Create a table message"""
        return cls(
            content={
                "columns": columns,
                "rows": rows
            },
            content_type="application/vnd.table+json",
            kind=MessageKind.TABLE,
            **kwargs
        )
    
    @classmethod
    def create_image(
        cls, 
        image_url: str = None,
        image_data: bytes = None,
        alt_text: str = "",
        **kwargs
    ) -> "Message":
        """Create an image message"""
        if image_data and len(image_data) < 100_000:  # <100KB: use data URI
            import base64
            b64 = base64.b64encode(image_data).decode()
            return cls(
                content=f"data:image/png;base64,{b64}",
                content_type="image/png",
                **kwargs
            )
        else:  # Large files: use attachment
            attachment = MessageAttachment(
                content_type="image/png",
                content_url=image_url,
                content_data=image_data if image_data and len(image_data) < 1_000_000 else None,
                metadata={"alt_text": alt_text}
            )
            return cls(
                content={"attachment_id": attachment.id, "alt_text": alt_text},
                content_type="image/png",
                attachments=[attachment],
                **kwargs
            )


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
```

### Message Role (Who)

```python
class MessageRole(str, Enum):
    USER = "user"           # Human user input
    ASSISTANT = "assistant" # AI/system response
    SYSTEM = "system"       # System-generated (welcome, notifications)
    TOOL = "tool"          # Tool execution results (MCP, functions)
    COMMAND = "command"    # Special commands (internal use)
```

### Message Kind (What)

```python
class MessageKind(str, Enum):
    CHAT = "chat"                    # Normal conversation message
    SLASH_COMMAND = "slash_command"  # User typed /command
    TOOL_RESULT = "tool_result"      # Result from MCP/tool execution
    NOTIFICATION = "notification"    # System notification to user
    DEBUG = "debug"                  # Debug/trace information
    QUERY_RESULT = "query_result"    # SQL query execution result
    CHART = "chart"                  # Chart/visualization data
    TABLE = "table"                  # Table data
    
    # Agentic flow support
    EXECUTION_PLAN = "execution_plan"      # Multi-step execution plan
    PLAN_APPROVAL = "plan_approval"        # User approval/rejection of plan
    PLAN_STEP = "plan_step"                # Individual step in execution
    CLARIFICATION = "clarification"        # Request for user input/decision
    CLARIFICATION_RESPONSE = "clarification_response"  # User's response to clarification
```

### Message Status

```python
class MessageStatus(str, Enum):
    PENDING = "pending"     # Message created, not processed
    PROCESSING = "processing"  # Currently being processed
    COMPLETED = "completed"    # Successfully completed
    FAILED = "failed"          # Processing failed
    CANCELLED = "cancelled"    # User cancelled
```

### Message Persistence

The `persistent` field determines whether a message should be stored in the database or only exist in-memory/SSE stream.

**Persistent Messages** (`persistent=True`, stored in DB):
- `chat` - Conversational messages for history
- `query_result` - Query results for replay/audit
- `execution_plan` - Plans need to be referenced later
- `plan_approval` - User decisions must be recorded
- `clarification` - Questions asked during execution
- `clarification_response` - User answers to clarifications
- `tool_result` - Tool outputs for context/debugging
- `slash_command` - Commands like `/new`, `/help` for history

**Transient Messages** (`persistent=False`, SSE/memory only):
- `notification` - Temporary user notifications ("Query taking longer...")
- `plan_step` - Real-time progress updates (redundant with plan stored)
- `status` - Processing status updates (ephemeral)
- `debug` - Debug info (unless debugging mode enabled)

```python
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

# Factory methods set persistence automatically
@classmethod
def create_notification(cls, text: str, **kwargs) -> "Message":
    """Create a transient notification message"""
    return cls(
        content=text,
        content_type="text/plain",
        kind=MessageKind.NOTIFICATION,
        persistent=False,  # Not stored in DB
        **kwargs
    )

@classmethod
def create_plan_step_update(cls, plan_id: str, step_id: str, **kwargs) -> "Message":
    """Create a transient step progress update"""
    return cls(
        content={
            "plan_id": plan_id,
            "step_id": step_id,
            "status": "running"
        },
        kind=MessageKind.PLAN_STEP,
        persistent=False,  # Not stored, just streamed via SSE
        **kwargs
    )
```

### Role + Kind Combinations (Examples)

| Role | Kind | Example Use Case |
|------|------|------------------|
| `user` | `chat` | Normal user question: "Show me top traders" |
| `user` | `slash_command` | User types: `/new` or `/help` |
| `assistant` | `chat` | AI text response |
| `assistant` | `query_result` | SQL query results with metadata |
| `assistant` | `chart` | Generated chart/visualization |
| `assistant` | `notification` | "Query is taking longer than expected..." |
| `system` | `chat` | Welcome message on session start |
| `system` | `notification` | "New feature available!" |
| `tool` | `tool_result` | MCP `get_database_overview` result |
| `tool` | `debug` | MCP call trace, prompt hashes |
| `assistant` | `execution_plan` | Multi-step execution plan for complex query |
| `user` | `plan_approval` | User approves/rejects execution plan |
| `assistant` | `plan_step` | Progress update for step execution |
| `assistant` | `clarification` | Ask user for decision mid-execution |
| `user` | `clarification_response` | User answers clarification question |

## Database Schema

### New Tables

```sql
-- Messages table (replaces request-response pairs)
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    
    -- Content (polymorphic: text, JSON, or reference to attachment)
    content JSONB NOT NULL,
    content_type VARCHAR(100) DEFAULT 'text/markdown',
    
    -- Classification
    role VARCHAR(50) NOT NULL,
    kind VARCHAR(50) NOT NULL,
    persistent BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Metadata
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    
    -- Relationships
    parent_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    thread_id UUID,
    tags TEXT[] DEFAULT '{}',
    
    -- Status
    status VARCHAR(50) DEFAULT 'pending',
    error TEXT,
    
    -- Indexes
    INDEX idx_messages_session (session_id, created_at),
    INDEX idx_messages_thread (thread_id),
    INDEX idx_messages_parent (parent_id),
    INDEX idx_messages_role_kind (role, kind)
);

-- Query metadata (linked to specific messages)
-- Note: This is SEPARATE from v1's `query` table
-- v1: query table (immutable SQL artifacts) + QueryMetadata (mutable, session-level)
-- v2: message_queries (immutable, message-level) + reuses QueryMetadata model
CREATE TABLE message_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    
    -- Core query details (similar to v1 Query model)
    sql_query TEXT NOT NULL,
    row_count INTEGER,
    execution_time_ms INTEGER,
    
    -- Lineage & provenance (existing fields from v1)
    prompt_hash VARCHAR(64),
    mcp_call_hash VARCHAR(64),
    profile VARCHAR(100),
    
    -- Link to v1 query table (for backward compatibility)
    v1_query_id UUID,  -- References v1 query.query_id if migrated/linked
    
    -- Extended metadata (can store v1 QueryMetadata fields as JSONB)
    metadata JSONB DEFAULT '{}',  -- Can include: summary, columns, explanation, etc.
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    INDEX idx_message_queries_message (message_id),
    INDEX idx_message_queries_v1_query (v1_query_id)
);

-- Message attachments (for multimodal support)
CREATE TABLE message_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    
    -- Attachment details
    content_type VARCHAR(100) NOT NULL,
    content_url TEXT,  -- S3 URL or data URI
    content_data BYTEA,  -- Small inline data
    
    -- Metadata
    filename VARCHAR(255),
    size_bytes INTEGER,
    metadata JSONB DEFAULT '{}',
    
    INDEX idx_message_attachments_message (message_id)
);
```

### Existing Tables

#### Sessions Table (Modified)
```sql
-- Add api_version to sessions table
ALTER TABLE sessions ADD COLUMN api_version VARCHAR(10) DEFAULT 'v1';

-- Migration: Backfill existing sessions as v1
UPDATE sessions SET api_version = 'v1' WHERE api_version IS NULL;
```

The `sessions` table is **shared between v1 and v2**:
- v1 sessions have `api_version = 'v1'` and use `requests` table
- v2 sessions have `api_version = 'v2'` and use `messages` table
- Existing sessions will be backfilled as `v1` during migration

#### Unchanged Tables
- `requests` - Keep for v1 API (InteractiveFlow)
- `query` - Keep for v1 API (immutable SQL artifacts)
- All other existing tables remain unchanged

### v1 vs v2 Query Model Comparison

Understanding how v2's query model differs from v1's approach:

#### v1 Query Architecture (Session-Centric)

```
Session (1) ─┬─> Request (N)
             │      └─> Query (0..1, immutable)
             │           ├─ query_id (UUID)
             │           ├─ sql (TEXT)
             │           ├─ row_count
             │           └─ columns (JSONB)
             │
             └─> QueryMetadata (1, mutable, session-level)
                   ├─ summary
                   ├─ query_follow_ups
                   ├─ columns
                   └─ refs
```

**v1 Characteristics**:
- `query` table: Immutable SQL artifacts generated through user-agent iterations
- `QueryMetadata`: Mutable, session-level, progressively updated
- `query` attached to `request` (session item)
- QueryMetadata attached to session (global)

#### v2 Query Architecture (Message-Centric)

```
Session (1) ─> Messages (N)
                  └─> Message (kind=query_result)
                        └─> message_queries (0..1)
                              ├─ sql_query (TEXT)
                              ├─ row_count
                              ├─ execution_time_ms
                              ├─ prompt_hash, mcp_call_hash
                              ├─ v1_query_id (UUID, optional link)
                              └─ metadata (JSONB)
                                   ├─ summary
                                   ├─ columns (reuse v1 Column model)
                                   ├─ explanation
                                   └─ query_follow_ups
```

**v2 Characteristics**:
- `message_queries`: Immutable, message-level (one per query result message)
- No session-level QueryMetadata (each message is self-contained)
- Query metadata stored in `message_queries.metadata` JSONB
- Can reference v1 `query` via `v1_query_id` for backward compat

### Reusing v1 Models in v2

v2 **reuses** existing v1 Pydantic models without modification:

```python
# From v1 (fm_app/api/model.py) - UNCHANGED
class Column(BaseModel):
    id: str = None
    summary: Optional[str] = None
    column_name: Optional[str] = None
    column_alias: Optional[str] = None
    column_type: Optional[str] = None
    column_description: Optional[str] = None

class QueryMetadata(BaseModel):
    id: Optional[UUID] = None
    summary: Optional[str] = None
    sql: Optional[str] = None
    query_follow_ups: Optional[list[str]] = None
    data_follow_ups: Optional[list[str]] = None
    columns: Optional[list[Column]] = None
    parents: Optional[list[UUID]] = None
    result: Optional[str] = None
    explanation: Optional[dict[str, Any]] = None
    row_count: Optional[int] = None
    refs: Optional[Refs] = None
    view: Optional[View] = None
    description: Optional[str] = None

# v2 stores QueryMetadata fields in message_queries.metadata
class MessageQuery(BaseModel):
    """v2 query model - wraps v1 concepts"""
    id: UUID
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
```

### Message Content for Query Results

Query result messages store data using v1 models:

```python
from fm_app.api.model import Column, QueryMetadata

# Create query result message
msg = Message(
    role=MessageRole.ASSISTANT,
    kind=MessageKind.QUERY_RESULT,
    content={
        "columns": [
            Column(
                id="wallet",
                column_name="wallet",
                column_type="string",
                column_description="Wallet address"
            ).dict(),
            Column(
                id="volume",
                column_name="total_volume",
                column_type="number"
            ).dict()
        ],
        "row_count": 5000,
        "strategy": "paginated",
        "preview": [...],  # First 100 rows
        "paginated_url": "/api/v2/data/q_123"
    },
    content_type="application/vnd.semanticgrid.table+json",
    metadata={
        "query_id": "q_123",
        "sql": "SELECT wallet, SUM(volume) as total_volume ...",
        "summary": "Top traders by volume"
    }
)

# Link to message_queries
message_query = MessageQuery(
    message_id=msg.id,
    sql_query="SELECT wallet, SUM(volume) as total_volume ...",
    row_count=5000,
    execution_time_ms=1234,
    prompt_hash="abc123...",
    mcp_call_hash="def456...",
    profile="wh_v2",
    metadata={
        "summary": "Top traders by volume",
        "columns": msg.content["columns"],  # Reuses v1 Column model
        "query_follow_ups": [
            "Show me their trading history",
            "What tokens did they trade?"
        ]
    }
)
```

### Migration Path: v1 Query → v2 Message

If linking existing v1 queries to v2 messages:

```python
async def link_v1_query_to_v2_message(
    v1_query_id: UUID,
    message_id: UUID
) -> MessageQuery:
    """
    Link existing v1 query to v2 message
    Useful for migrating historical data or hybrid flows
    """
    
    # Fetch v1 query
    v1_query = await db.query.find_one({"query_id": v1_query_id})
    
    # Create message_queries entry linking to v1
    message_query = await db.message_queries.create({
        "message_id": message_id,
        "sql_query": v1_query["sql"],
        "row_count": v1_query["row_count"],
        "v1_query_id": v1_query_id,  # Link to v1
        "metadata": {
            "summary": v1_query.get("summary"),
            "columns": v1_query.get("columns"),
            "migrated_from_v1": True
        }
    })
    
    return message_query
```

### Key Differences Summary

| Aspect | v1 | v2 |
|--------|----|----|
| **Scope** | Session-level QueryMetadata | Message-level message_queries |
| **Mutability** | QueryMetadata is mutable | message_queries is immutable |
| **Attachment** | Query → Request → Session | message_queries → Message → Session |
| **Storage** | Separate `query` + QueryMetadata | Single `message_queries` with metadata JSONB |
| **Reusability** | QueryMetadata shared across session | Each query result is self-contained |
| **Models** | QueryMetadata, Column, View | **Reuses same models** in JSONB |

### Why This Design?

✅ **Message-centric** - Each query result is a complete, self-contained message  
✅ **Immutable** - Query results don't change (new queries = new messages)  
✅ **Backward compatible** - Reuses v1 Column, QueryMetadata models  
✅ **Flexible** - Metadata JSONB can store any v1 QueryMetadata fields  
✅ **Linkable** - Can reference v1 queries via `v1_query_id` if needed  
✅ **Audit trail** - Full query history in messages table  
✅ **Clean separation** - v1 and v2 don't interfere with each other

## API Design

### v2 Endpoints

```python
# New v2 API routes (fm-app)
POST   /api/v2/sessions                    # Create new session
GET    /api/v2/sessions/{session_id}       # Get session with messages
POST   /api/v2/sessions/{session_id}/messages  # Send message
GET    /api/v2/sessions/{session_id}/messages  # List messages
GET    /api/v2/messages/{message_id}       # Get specific message
PATCH  /api/v2/messages/{message_id}       # Update message status
DELETE /api/v2/messages/{message_id}       # Delete message

# Server-Sent Events (SSE) for real-time streaming
GET    /api/v2/sessions/{session_id}/stream   # SSE endpoint for messages & artifacts
```

### v1 Endpoints (Unchanged)

```python
# Existing v1 API routes continue to work
POST   /api/v1/grid/chat/{id}
GET    /api/v1/grid/{id}
# ... all other existing endpoints
```

### Request/Response Examples

#### Create Session (v2)

```http
POST /api/v2/sessions
Content-Type: application/json

{
  "client": "acme",
  "environment": "production"
}

Response:
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2025-01-08T10:00:00Z",
  "messages": [
    {
      "id": "msg_001",
      "role": "system",
      "kind": "chat",
      "content": "# Welcome!\n\nYou're starting a new session...",
      "created_at": "2025-01-08T10:00:00Z",
      "status": "completed"
    }
  ]
}
```

#### Send User Message (v2)

```http
POST /api/v2/sessions/{session_id}/messages
Content-Type: application/json

{
  "role": "user",
  "kind": "chat",
  "content": "Show me top 10 traders by volume",
  "parent_id": null,
  "thread_id": null
}

Response (streaming or immediate):
{
  "message_id": "msg_002",
  "status": "processing",
  "assistant_messages": [
    {
      "id": "msg_003",
      "role": "assistant",
      "kind": "chat",
      "content": "I'll query the database for top traders...",
      "parent_id": "msg_002",
      "status": "completed"
    },
    {
      "id": "msg_004",
      "role": "tool",
      "kind": "tool_result",
      "content": "Executed SQL query successfully",
      "parent_id": "msg_002",
      "metadata": {
        "tool": "db_meta.execute_query",
        "execution_time_ms": 234
      },
      "status": "completed"
    },
    {
      "id": "msg_005",
      "role": "assistant",
      "kind": "query_result",
      "content": "Top 10 traders by volume",
      "parent_id": "msg_002",
      "metadata": {
        "query_id": "query_001",
        "row_count": 10,
        "columns": [...]
      },
      "status": "completed"
    }
  ]
}
```

#### Send Slash Command (v2)

```http
POST /api/v2/sessions/{session_id}/messages
Content-Type: application/json

{
  "role": "user",
  "kind": "slash_command",
  "content": "/help"
}

Response:
{
  "message_id": "msg_006",
  "assistant_messages": [
    {
      "id": "msg_007",
      "role": "assistant",
      "kind": "chat",
      "content": "# Database Overview\n\nThis database contains...",
      "parent_id": "msg_006",
      "metadata": {
        "command": "help",
        "source": "db_meta.database_overview"
      },
      "status": "completed"
    }
  ]
}
```

## VersatileFlow Implementation

### Flow Architecture

```python
class VersatileFlow:
    """
    v2 flow handler that processes messages flexibly
    Replaces the rigid request-response pattern of InteractiveFlow
    """
    
    async def process_message(
        self,
        session_id: str,
        message: Message,
        settings: Settings,
        logger: Logger
    ) -> List[Message]:
        """
        Process a single message and return assistant responses
        Can return 0, 1, or multiple messages
        """
        
        # Route based on message kind
        if message.kind == MessageKind.SLASH_COMMAND:
            return await self.handle_slash_command(message)
        
        elif message.kind == MessageKind.CHAT:
            return await self.handle_chat_message(message)
        
        else:
            raise ValueError(f"Unsupported message kind: {message.kind}")
    
    async def handle_slash_command(self, message: Message) -> List[Message]:
        """Handle slash commands like /new, /help"""
        command = message.content.strip()
        
        if command == "/new":
            # Return welcome message (deterministic, no LLM)
            overview = await self.get_database_overview(mode="new")
            return [Message(
                role=MessageRole.ASSISTANT,
                kind=MessageKind.CHAT,
                content=overview,
                parent_id=message.id,
                metadata={"command": "new", "skip_llm": True}
            )]
        
        elif command == "/help":
            # Return enhanced help (with LLM)
            help_response = await self.generate_help_response()
            return [Message(
                role=MessageRole.ASSISTANT,
                kind=MessageKind.CHAT,
                content=help_response,
                parent_id=message.id,
                metadata={"command": "help"}
            )]
        
        else:
            raise ValueError(f"Unknown command: {command}")
    
    async def handle_chat_message(self, message: Message) -> List[Message]:
        """
        Handle regular chat message
        Returns multiple messages for:
        1. Initial acknowledgment (optional)
        2. Tool execution results (optional)
        3. Final response with query results
        """
        responses = []
        
        # Step 1: Plan and generate SQL
        planner_result = await self.plan_query(message)
        
        # Step 2: Execute SQL via MCP
        tool_message = Message(
            role=MessageRole.TOOL,
            kind=MessageKind.TOOL_RESULT,
            content=f"Executing query...",
            parent_id=message.id,
            metadata={"tool": "db_meta.execute_query"},
            status=MessageStatus.PROCESSING
        )
        responses.append(tool_message)
        
        query_result = await self.execute_query(planner_result.sql)
        tool_message.status = MessageStatus.COMPLETED
        tool_message.metadata["execution_time_ms"] = query_result.execution_time
        
        # Step 3: Return formatted results
        result_message = Message(
            role=MessageRole.ASSISTANT,
            kind=MessageKind.QUERY_RESULT,
            content=self.format_results(query_result),
            parent_id=message.id,
            metadata={
                "query_id": query_result.id,
                "row_count": query_result.row_count,
                "sql": query_result.sql
            },
            status=MessageStatus.COMPLETED
        )
        responses.append(result_message)
        
        return responses
```

### Celery Task Structure

```python
@celery_app.task(name="versatile_flow.process_message")
def process_message_task(
    session_id: str,
    message_dict: dict,
    settings_dict: dict
):
    """
    Celery task for VersatileFlow
    Similar to interactive_flow_task but for v2 messages
    """
    message = Message(**message_dict)
    settings = Settings(**settings_dict)
    logger = get_logger(session_id)
    
    flow = VersatileFlow()
    
    try:
        # Process message
        response_messages = await flow.process_message(
            session_id=session_id,
            message=message,
            settings=settings,
            logger=logger
        )
        
        # Save all response messages to DB
        for resp_msg in response_messages:
            save_message(session_id, resp_msg)
        
        return {
            "status": "success",
            "message_ids": [msg.id for msg in response_messages]
        }
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        
        # Create error message
        error_msg = Message(
            role=MessageRole.ASSISTANT,
            kind=MessageKind.NOTIFICATION,
            content=f"Error: {str(e)}",
            parent_id=message.id,
            status=MessageStatus.FAILED,
            error=str(e)
        )
        save_message(session_id, error_msg)
        
        raise
```

## Agentic Flows with Execution Plans

### Overview

Modern agentic workflows require support for complex, multi-step execution with user interaction. The v2 message architecture natively supports:

1. **Plan creation** - Assistant proposes execution plan with multiple steps
2. **User consent** - Request approval before execution (auto/manual modes)
3. **Progressive execution** - Execute steps with real-time progress updates
4. **Mid-execution clarification** - Ask questions and make decisions during execution
5. **Plan adaptation** - Modify plan based on intermediate results or user input

### Message Flow for Agentic Execution

```
User Question
    ↓
Assistant creates EXECUTION_PLAN
    ↓
[Manual mode] User sends PLAN_APPROVAL (approve/reject/modify)
    ↓
Assistant executes steps, sending PLAN_STEP messages for each
    ↓
[If needed] Assistant sends CLARIFICATION
    ↓
[If needed] User sends CLARIFICATION_RESPONSE
    ↓
Continue execution with updated context
    ↓
Final QUERY_RESULT message(s)
```

### Execution Plan Model

```python
class ExecutionPlanStep(BaseModel):
    """Single step in an execution plan"""
    step_id: str
    step_number: int
    description: str
    step_type: Literal["query", "analysis", "transformation", "decision"]
    
    # What this step will do
    action: str  # Human-readable description
    
    # Dependencies
    depends_on: List[str] = Field(default_factory=list)  # step_ids this depends on
    
    # Estimated cost/time
    estimated_time_seconds: Optional[int] = None
    estimated_row_count: Optional[int] = None
    
    # Status tracking
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionPlan(BaseModel):
    """Multi-step execution plan for complex queries"""
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    
    # Plan metadata
    description: str  # Overall goal
    steps: List[ExecutionPlanStep]
    
    # Execution mode
    requires_approval: bool = True  # If False, auto-execute
    
    # Risk assessment
    complexity: Literal["low", "medium", "high"] = "medium"
    estimated_total_time_seconds: Optional[int] = None
    
    # State
    approved: Optional[bool] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

### Example: Complex Query with Execution Plan

#### User Query
```python
msg = Message.create_text(
    text="Find wallets that increased trading volume by >50% in last 30 days, "
         "then analyze their token preferences and create a similarity graph",
    role=MessageRole.USER,
    kind=MessageKind.CHAT,
    session_id=session_id
)
```

#### Assistant Proposes Plan
```python
plan = ExecutionPlan(
    description="Multi-step analysis: volume spike detection → preference analysis → similarity graph",
    requires_approval=True,
    complexity="high",
    estimated_total_time_seconds=45,
    steps=[
        ExecutionPlanStep(
            step_id="step_1",
            step_number=1,
            description="Identify wallets with volume increase >50%",
            step_type="query",
            action="Query trading history for last 60 days, calculate 30-day windows, filter by volume delta",
            estimated_time_seconds=10,
            estimated_row_count=500
        ),
        ExecutionPlanStep(
            step_id="step_2",
            step_number=2,
            description="Analyze token preferences for identified wallets",
            step_type="analysis",
            action="Query token holdings and trades for wallets from step 1",
            depends_on=["step_1"],
            estimated_time_seconds=15,
            estimated_row_count=5000
        ),
        ExecutionPlanStep(
            step_id="step_3",
            step_number=3,
            description="Calculate wallet similarity based on token overlap",
            step_type="transformation",
            action="Compute cosine similarity matrix from token preferences",
            depends_on=["step_2"],
            estimated_time_seconds=10
        ),
        ExecutionPlanStep(
            step_id="step_4",
            step_number=4,
            description="Generate similarity graph visualization",
            step_type="transformation",
            action="Create network graph with wallets as nodes, similarity as edges",
            depends_on=["step_3"],
            estimated_time_seconds=10
        )
    ]
)

msg_plan = Message(
    content=plan.model_dump(),
    content_type="application/vnd.semanticgrid.plan+json",
    role=MessageRole.ASSISTANT,
    kind=MessageKind.EXECUTION_PLAN,
    parent_id=user_message_id,
    status=MessageStatus.PENDING,
    metadata={
        "requires_approval": True,
        "complexity": "high"
    }
)
```

#### User Approves Plan
```python
msg_approval = Message(
    content={
        "plan_id": plan.plan_id,
        "approved": True,
        "modifications": None  # Could request changes
    },
    content_type="application/json",
    role=MessageRole.USER,
    kind=MessageKind.PLAN_APPROVAL,
    parent_id=msg_plan.id
)
```

#### Assistant Executes Steps with Progress Updates

```python
# Step 1 execution
msg_step1_start = Message.create_text(
    text="**Step 1/4**: Identifying wallets with volume increase >50%...",
    role=MessageRole.ASSISTANT,
    kind=MessageKind.PLAN_STEP,
    parent_id=user_message_id,
    metadata={
        "plan_id": plan.plan_id,
        "step_id": "step_1",
        "step_number": 1,
        "status": "running"
    }
)

# Step 1 complete
msg_step1_complete = Message(
    content={
        "plan_id": plan.plan_id,
        "step_id": "step_1",
        "status": "completed",
        "result_summary": "Found 487 wallets with volume spike",
        "row_count": 487
    },
    content_type="application/json",
    role=MessageRole.ASSISTANT,
    kind=MessageKind.PLAN_STEP,
    parent_id=user_message_id,
    metadata={"step_number": 1}
)

# ... continue for other steps
```

#### Mid-Execution Clarification

```python
# During step 2, assistant needs clarification
msg_clarification = Message.create_text(
    text="I found that 23% of these wallets hold meme tokens. "
         "Should I include meme tokens in the preference analysis, or exclude them?",
    role=MessageRole.ASSISTANT,
    kind=MessageKind.CLARIFICATION,
    parent_id=user_message_id,
    metadata={
        "plan_id": plan.plan_id,
        "step_id": "step_2",
        "clarification_type": "decision",
        "options": ["include_meme_tokens", "exclude_meme_tokens"]
    }
)

# User responds
msg_clarification_response = Message.create_text(
    text="Exclude meme tokens",
    role=MessageRole.USER,
    kind=MessageKind.CLARIFICATION_RESPONSE,
    parent_id=msg_clarification.id,
    metadata={
        "selected_option": "exclude_meme_tokens"
    }
)

# Assistant continues with updated context
```

#### Final Result

```python
# After all steps complete
msg_final = Message(
    content={
        "columns": [...],
        "row_count": 487,
        "strategy": "embedded",
        "embedded_data": [...]
    },
    content_type=DataMimeType.TABLE_JSON,
    role=MessageRole.ASSISTANT,
    kind=MessageKind.QUERY_RESULT,
    parent_id=user_message_id,
    metadata={
        "plan_id": plan.plan_id,
        "execution_time_seconds": 42,
        "steps_completed": 4
    }
)
```

### Auto-Execution Mode

For trusted operations or user preference, skip approval:

```python
# User setting (stored in session or user profile)
user_settings = {
    "agentic_execution_mode": "auto",  # "auto" or "manual"
    "auto_execute_max_complexity": "medium"  # "low", "medium", "high"
}

# In VersatileFlow
if plan.complexity == "low" or (
    user_settings["agentic_execution_mode"] == "auto" and 
    complexity_level(plan.complexity) <= complexity_level(user_settings["auto_execute_max_complexity"])
):
    # Skip approval, execute immediately
    plan.requires_approval = False
    plan.approved = True
else:
    # Request approval
    plan.requires_approval = True
```

### Database Support

The existing message schema fully supports agentic flows:

```sql
-- Plan tracking via message metadata
SELECT * FROM messages 
WHERE kind = 'execution_plan' 
  AND metadata->>'plan_id' = 'plan_123';

-- Get all steps for a plan
SELECT * FROM messages 
WHERE kind = 'plan_step' 
  AND metadata->>'plan_id' = 'plan_123'
ORDER BY metadata->>'step_number';

-- Check if plan was approved
SELECT * FROM messages 
WHERE kind = 'plan_approval' 
  AND metadata->>'plan_id' = 'plan_123';

-- Find clarifications and responses
SELECT * FROM messages 
WHERE kind IN ('clarification', 'clarification_response')
  AND metadata->>'plan_id' = 'plan_123'
ORDER BY created_at;
```

### VersatileFlow Integration

```python
class VersatileFlow:
    async def handle_chat_message(self, message: Message) -> List[Message]:
        """Enhanced to support agentic execution"""
        
        # Analyze query complexity
        complexity = await self.analyze_complexity(message.text)
        
        if complexity in ["medium", "high"]:
            # Create execution plan
            plan = await self.create_execution_plan(message.text, complexity)
            
            # Check if approval needed
            if self.requires_approval(plan):
                # Return plan for user review
                return [Message(
                    content=plan.model_dump(),
                    content_type="application/vnd.semanticgrid.plan+json",
                    kind=MessageKind.EXECUTION_PLAN,
                    parent_id=message.id,
                    ...
                )]
            else:
                # Auto-execute
                return await self.execute_plan(plan, message.id)
        else:
            # Simple query - execute directly
            return await super().handle_chat_message(message)
    
    async def handle_plan_approval(self, message: Message) -> List[Message]:
        """Handle user approval/rejection of execution plan"""
        approval_data = message.data
        plan_id = approval_data["plan_id"]
        
        if approval_data["approved"]:
            # Retrieve and execute plan
            plan = await self.get_plan(plan_id)
            return await self.execute_plan(plan, message.parent_id)
        else:
            # Plan rejected
            return [Message.create_text(
                text="Plan cancelled. Would you like me to propose an alternative approach?",
                role=MessageRole.ASSISTANT,
                kind=MessageKind.CHAT,
                parent_id=message.parent_id
            )]
    
    async def execute_plan(
        self, 
        plan: ExecutionPlan, 
        parent_id: str
    ) -> List[Message]:
        """Execute plan steps with progress updates"""
        messages = []
        
        for step in plan.steps:
            # Check dependencies
            if not await self.dependencies_met(step, plan):
                continue
            
            # Send step start notification
            messages.append(Message.create_text(
                text=f"**Step {step.step_number}/{len(plan.steps)}**: {step.description}...",
                role=MessageRole.ASSISTANT,
                kind=MessageKind.PLAN_STEP,
                parent_id=parent_id,
                metadata={"plan_id": plan.plan_id, "step_id": step.step_id, "status": "running"}
            ))
            
            # Execute step
            try:
                result = await self.execute_step(step)
                step.status = "completed"
                step.result = result
                
                # Check if clarification needed
                if result.get("needs_clarification"):
                    clarification_msg = Message.create_text(
                        text=result["clarification_question"],
                        role=MessageRole.ASSISTANT,
                        kind=MessageKind.CLARIFICATION,
                        parent_id=parent_id,
                        metadata={"plan_id": plan.plan_id, "step_id": step.step_id}
                    )
                    messages.append(clarification_msg)
                    
                    # Wait for user response (handled by separate message)
                    return messages
                
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                messages.append(Message.create_text(
                    text=f"❌ Step {step.step_number} failed: {e}",
                    role=MessageRole.ASSISTANT,
                    kind=MessageKind.PLAN_STEP,
                    parent_id=parent_id,
                    status=MessageStatus.FAILED
                ))
                break
        
        # All steps complete - return final result
        final_result = await self.compile_plan_results(plan)
        messages.append(final_result)
        
        return messages
```

### Frontend Integration

```typescript
// Execution plan component
function ExecutionPlanView({ message }: { message: Message }) {
  const plan = message.content as ExecutionPlan;
  const [approved, setApproved] = useState<boolean | null>(null);
  
  const handleApprove = async () => {
    await sendMessage({
      role: MessageRole.USER,
      kind: MessageKind.PLAN_APPROVAL,
      content: {
        plan_id: plan.plan_id,
        approved: true
      },
      parent_id: message.id
    });
    setApproved(true);
  };
  
  return (
    <Card>
      <Typography variant="h6">Execution Plan</Typography>
      <Typography color="textSecondary">{plan.description}</Typography>
      
      <Chip 
        label={`${plan.complexity} complexity`} 
        color={plan.complexity === 'high' ? 'error' : 'default'}
      />
      <Chip label={`~${plan.estimated_total_time_seconds}s`} />
      
      <Stepper orientation="vertical">
        {plan.steps.map((step, idx) => (
          <Step key={step.step_id} active={step.status === 'running'} completed={step.status === 'completed'}>
            <StepLabel error={step.status === 'failed'}>
              {step.description}
            </StepLabel>
            <StepContent>
              <Typography variant="body2">{step.action}</Typography>
              {step.estimated_row_count && (
                <Typography variant="caption">
                  ~{step.estimated_row_count.toLocaleString()} rows
                </Typography>
              )}
            </StepContent>
          </Step>
        ))}
      </Stepper>
      
      {plan.requires_approval && approved === null && (
        <Stack direction="row" spacing={2} mt={2}>
          <Button variant="contained" onClick={handleApprove}>
            Approve & Execute
          </Button>
          <Button variant="outlined" onClick={() => setApproved(false)}>
            Cancel
          </Button>
        </Stack>
      )}
    </Card>
  );
}

// Clarification component
function ClarificationView({ message }: { message: Message }) {
  const options = message.metadata.options as string[];
  
  const handleResponse = async (option: string) => {
    await sendMessage({
      role: MessageRole.USER,
      kind: MessageKind.CLARIFICATION_RESPONSE,
      content: option,
      parent_id: message.id,
      metadata: { selected_option: option }
    });
  };
  
  return (
    <Card>
      <Typography>{message.content}</Typography>
      <Stack direction="row" spacing={1} mt={2}>
        {options.map(opt => (
          <Button key={opt} onClick={() => handleResponse(opt)}>
            {opt.replace(/_/g, ' ')}
          </Button>
        ))}
      </Stack>
    </Card>
  );
}
```

### Benefits

✅ **Transparent execution** - User sees exactly what will happen before it runs  
✅ **User control** - Approve/reject/modify plans before execution  
✅ **Progressive feedback** - Real-time updates as steps complete  
✅ **Interactive refinement** - Clarifications and decisions during execution  
✅ **Audit trail** - Full execution history in message thread  
✅ **Flexible modes** - Auto-execute for simple queries, manual for complex  
✅ **Error recovery** - Failed steps don't break entire flow  
✅ **Complexity awareness** - System understands and communicates risk  

## LLM API Compatibility

### Overview

Our v2 message schema is designed to map cleanly to major LLM provider APIs (OpenAI, Anthropic, Google Gemini) while providing additional flexibility for our use case (execution plans, clarifications, etc.).

### Role Mapping to LLM APIs

| Our Role | OpenAI | Anthropic Claude | Google Gemini | Purpose |
|----------|--------|------------------|---------------|---------|
| `user` | `user` | `user` | `user` | Human user input |
| `assistant` | `assistant` | `assistant` | `model` | AI/system responses |
| `system` | `system` | N/A (uses top-level `system` param) | `system` (OpenAI compat mode) | System instructions |
| `tool` | `tool` | `user` with `tool_result` content | `function` | Tool execution results |
| `command` | *filtered out* | *filtered out* | *filtered out* | Internal only |

### Message Kind to LLM Conversion

When calling LLM APIs, we convert our rich `MessageKind` taxonomy to standard LLM roles:

```python
def convert_to_llm_messages(
    messages: List[Message],
    provider: Literal["openai", "anthropic", "gemini"]
) -> List[Dict[str, Any]]:
    """
    Convert our v2 messages to LLM provider format
    Filter out internal message kinds, map roles correctly
    """
    llm_messages = []
    
    for msg in messages:
        # Skip internal/command messages
        if msg.role == MessageRole.COMMAND:
            continue
        
        # Skip non-conversational kinds
        if msg.kind in [
            MessageKind.EXECUTION_PLAN,
            MessageKind.PLAN_APPROVAL,
            MessageKind.PLAN_STEP,
            MessageKind.NOTIFICATION,
            MessageKind.DEBUG
        ]:
            continue
        
        # Map our roles to provider roles
        if provider == "openai":
            llm_msg = convert_to_openai(msg)
        elif provider == "anthropic":
            llm_msg = convert_to_anthropic(msg)
        elif provider == "gemini":
            llm_msg = convert_to_gemini(msg)
        
        llm_messages.append(llm_msg)
    
    return llm_messages


def convert_to_openai(msg: Message) -> Dict[str, Any]:
    """Convert to OpenAI Chat Completion format"""
    
    # Map role
    role_map = {
        MessageRole.USER: "user",
        MessageRole.ASSISTANT: "assistant",
        MessageRole.SYSTEM: "system",
        MessageRole.TOOL: "tool"
    }
    
    result = {
        "role": role_map[msg.role],
        "content": msg.text or json.dumps(msg.data) if msg.data else ""
    }
    
    # Add tool call metadata if present
    if msg.kind == MessageKind.TOOL_RESULT and msg.metadata.get("tool_call_id"):
        result["tool_call_id"] = msg.metadata["tool_call_id"]
        result["name"] = msg.metadata.get("tool_name", "unknown")
    
    return result


def convert_to_anthropic(msg: Message) -> Dict[str, Any]:
    """Convert to Anthropic Messages API format"""
    
    # Anthropic doesn't have a 'system' role in messages
    # System prompts go in a separate 'system' parameter
    role_map = {
        MessageRole.USER: "user",
        MessageRole.ASSISTANT: "assistant",
        MessageRole.TOOL: "user",  # Tool results sent as user messages with tool_result content
        MessageRole.SYSTEM: "user"  # Fallback if system message in conversation
    }
    
    content = msg.text or json.dumps(msg.data) if msg.data else ""
    
    result = {
        "role": role_map[msg.role],
        "content": content
    }
    
    # Handle tool results
    if msg.kind == MessageKind.TOOL_RESULT:
        result["content"] = [
            {
                "type": "tool_result",
                "tool_use_id": msg.metadata.get("tool_use_id"),
                "content": content
            }
        ]
    
    return result


def convert_to_gemini(msg: Message) -> Dict[str, Any]:
    """Convert to Google Gemini format"""
    
    role_map = {
        MessageRole.USER: "user",
        MessageRole.ASSISTANT: "model",  # Gemini uses 'model' instead of 'assistant'
        MessageRole.SYSTEM: "system",  # In OpenAI compatibility mode
        MessageRole.TOOL: "function"
    }
    
    return {
        "role": role_map[msg.role],
        "parts": [{"text": msg.text or json.dumps(msg.data)}]
    }
```

### Conversational Context Building

When building context for LLM calls, filter and transform messages:

```python
async def build_llm_context(
    session_id: str,
    provider: Literal["openai", "anthropic", "gemini"],
    max_tokens: int = 4000
) -> List[Dict[str, Any]]:
    """
    Build LLM context from session messages
    Includes only relevant conversational messages
    """
    
    # Fetch all messages from session
    all_messages = await get_session_messages(session_id)
    
    # Filter to conversational messages only
    conversational_kinds = [
        MessageKind.CHAT,
        MessageKind.QUERY_RESULT,  # Include for context about previous queries
        MessageKind.CLARIFICATION,
        MessageKind.CLARIFICATION_RESPONSE,
        MessageKind.TOOL_RESULT  # Include tool results for context
    ]
    
    filtered_messages = [
        msg for msg in all_messages
        if msg.kind in conversational_kinds
    ]
    
    # Convert to LLM format
    llm_messages = convert_to_llm_messages(filtered_messages, provider)
    
    # Trim to fit within token budget (optional)
    llm_messages = trim_to_token_limit(llm_messages, max_tokens)
    
    return llm_messages


# Usage in VersatileFlow
class VersatileFlow:
    async def handle_chat_message(self, message: Message) -> List[Message]:
        """Process chat message with LLM"""
        
        # Build context from previous messages
        context = await build_llm_context(
            message.session_id,
            provider="anthropic",  # or from settings
            max_tokens=8000
        )
        
        # Add current user message
        context.append(convert_to_anthropic(message))
        
        # Call LLM
        if self.provider == "anthropic":
            response = await self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                system="You are a data analyst assistant...",  # System prompt
                messages=context
            )
        elif self.provider == "openai":
            # System message goes in messages array
            system_msg = {"role": "system", "content": "You are a data analyst assistant..."}
            response = await self.client.chat.completions.create(
                model="gpt-4",
                messages=[system_msg] + context
            )
        
        # Convert response back to our Message format
        assistant_message = Message.create_text(
            text=response.content[0].text,  # Anthropic format
            role=MessageRole.ASSISTANT,
            kind=MessageKind.CHAT,
            parent_id=message.id,
            session_id=message.session_id
        )
        
        return [assistant_message]
```

### Tool/Function Calling Integration

Our `tool` role and `tool_result` kind map to provider tool calling:

#### OpenAI Tool Calling
```python
# Assistant requests tool call
{
    "role": "assistant",
    "content": null,
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "get_database_overview",
                "arguments": "{\"mode\": \"help\"}"
            }
        }
    ]
}

# Our Message representation
Message(
    role=MessageRole.ASSISTANT,
    kind=MessageKind.CHAT,
    content={"tool_calls": [...]},
    metadata={"tool_call_id": "call_abc123"}
)

# Tool result returned
{
    "role": "tool",
    "tool_call_id": "call_abc123",
    "content": "Database contains 50 tables..."
}

# Our Message representation
Message(
    role=MessageRole.TOOL,
    kind=MessageKind.TOOL_RESULT,
    content="Database contains 50 tables...",
    metadata={"tool_call_id": "call_abc123", "tool_name": "get_database_overview"}
)
```

#### Anthropic Tool Calling
```python
# Assistant requests tool call
{
    "role": "assistant",
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01A09q90qw90lq917835lq9",
            "name": "get_database_overview",
            "input": {"mode": "help"}
        }
    ]
}

# Tool result returned (as user message)
{
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
            "content": "Database contains 50 tables..."
        }
    ]
}

# Our Message representation (same as OpenAI)
Message(
    role=MessageRole.TOOL,
    kind=MessageKind.TOOL_RESULT,
    content="Database contains 50 tables...",
    metadata={"tool_use_id": "toolu_01A09q90qw90lq917835lq9", "tool_name": "get_database_overview"}
)
```

### System Prompts

Each provider handles system prompts differently:

```python
def build_system_prompt(session: Session, user_settings: dict) -> str:
    """Build system prompt from templates"""
    return """
You are a data analyst assistant helping users explore blockchain data.

Available capabilities:
- Query generation from natural language
- Multi-step execution plans for complex queries
- Data analysis and insights

Current database: {database_name}
User preferences: {user_settings}
""".format(
        database_name=session.database,
        user_settings=json.dumps(user_settings)
    )


# OpenAI: Include as first message
messages = [
    {"role": "system", "content": build_system_prompt(session, user_settings)},
    *conversational_messages
]

# Anthropic: Separate 'system' parameter
client.messages.create(
    model="claude-sonnet-4-5-20250929",
    system=build_system_prompt(session, user_settings),
    messages=conversational_messages
)

# Gemini: System instruction parameter
client.generate_content(
    model="gemini-2.0-flash-exp",
    system_instruction=build_system_prompt(session, user_settings),
    contents=conversational_messages
)
```

### Message Kind Filtering by Use Case

Different LLM calls need different message histories:

```python
# For general chat: Include chat + clarifications
chat_context = filter_messages(
    all_messages,
    include_kinds=[
        MessageKind.CHAT,
        MessageKind.CLARIFICATION,
        MessageKind.CLARIFICATION_RESPONSE
    ]
)

# For query generation: Include chat + query results for context
query_context = filter_messages(
    all_messages,
    include_kinds=[
        MessageKind.CHAT,
        MessageKind.QUERY_RESULT,
        MessageKind.TOOL_RESULT
    ]
)

# For plan generation: Include everything except debug/internal
plan_context = filter_messages(
    all_messages,
    exclude_kinds=[
        MessageKind.DEBUG,
        MessageKind.NOTIFICATION,
        MessageKind.EXECUTION_PLAN,
        MessageKind.PLAN_APPROVAL,
        MessageKind.PLAN_STEP
    ]
)
```

### Message Persistence in Practice

```python
async def save_message(message: Message) -> Optional[Message]:
    """
    Save message to database if persistent
    Returns the message (with DB id if saved)
    """
    if not message.persistent:
        # Transient message - don't save to DB
        logger.debug(f"Skipping DB save for transient message: {message.kind}")
        return message
    
    # Save to database
    db_message = await db.messages.create({
        "id": message.id,
        "session_id": message.session_id,
        "content": message.content,
        "content_type": message.content_type,
        "role": message.role,
        "kind": message.kind,
        "persistent": message.persistent,
        "created_at": message.created_at,
        "metadata": message.metadata,
        "parent_id": message.parent_id,
        "thread_id": message.thread_id,
        "tags": message.tags,
        "status": message.status,
        "error": message.error
    })
    
    logger.info(f"Saved persistent message: {message.kind} ({message.id})")
    return message


# In VersatileFlow
class VersatileFlow:
    async def execute_plan(self, plan: ExecutionPlan, parent_id: str) -> List[Message]:
        """Execute plan with mix of persistent and transient messages"""
        messages = []
        
        for step in plan.steps:
            # Transient: Step start notification (just for SSE)
            step_start_msg = Message.create_plan_step_update(
                plan_id=plan.plan_id,
                step_id=step.step_id,
                role=MessageRole.ASSISTANT,
                session_id=self.session_id,
                parent_id=parent_id,
                metadata={"step_number": step.step_number, "status": "running"}
            )
            messages.append(step_start_msg)
            await self.queue.publish({
                "type": "message",
                "payload": {"message": step_start_msg.model_dump()}
            })
            # Not saved to DB (persistent=False)
            
            # Execute step
            result = await self.execute_step(step)
            
            # Persistent: Step completion (stored for audit trail)
            step_complete_msg = Message(
                content={
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "status": "completed",
                    "result_summary": result.summary
                },
                role=MessageRole.ASSISTANT,
                kind=MessageKind.PLAN_STEP,
                persistent=True,  # Store completion for history
                session_id=self.session_id,
                parent_id=parent_id,
                metadata={"step_number": step.step_number}
            )
            await save_message(step_complete_msg)  # Saved to DB
            messages.append(step_complete_msg)
            
        return messages
```

### Benefits of Persistence Field

✅ **Reduced DB writes** - Transient messages (notifications, progress) not stored  
✅ **Better performance** - Less I/O for ephemeral updates  
✅ **Cleaner history** - DB only contains meaningful conversation, not noise  
✅ **SSE efficiency** - Stream real-time updates without DB overhead  
✅ **Flexible retention** - Store what matters, discard what doesn't  
✅ **Debug control** - Debug messages can be persistent when debug mode enabled  

### Benefits of Our Schema

✅ **Provider-agnostic storage** - Single schema stores messages from any LLM  
✅ **Rich metadata** - Execution plans, clarifications, artifacts beyond basic chat  
✅ **Clean conversion** - Map to any provider's format without data loss  
✅ **Audit trail** - Full conversation history including internal steps  
✅ **Tool calling support** - Compatible with OpenAI, Anthropic, Gemini function calling  
✅ **System prompt flexibility** - Adapt to provider-specific patterns  
✅ **Future-proof** - Add new providers without schema changes  

## Real-Time Streaming with SSE

### Overview

Server-Sent Events (SSE) provide real-time streaming of messages and artifacts as they become available during execution. Unlike traditional request-response, SSE enables:

1. **Progressive message delivery** - Stream assistant messages as they're generated
2. **Artifact streaming** - Deliver query results, plan steps, and data chunks incrementally
3. **Status updates** - Real-time progress indicators during long operations
4. **Multiple responses** - Stream multiple messages for a single user request
5. **Automatic reconnection** - Browser handles reconnection on disconnect

### SSE vs Traditional Request-Response

| Aspect | Traditional | SSE Streaming |
|--------|-------------|---------------|
| **Response time** | Wait for complete processing | Immediate feedback |
| **User experience** | Loading spinner | Progressive updates |
| **Data availability** | All at once | As soon as ready |
| **Long operations** | Timeout risk | Continuous updates |
| **Multiple messages** | Not supported | Native support |

### SSE Endpoint

```python
GET /api/v2/sessions/{session_id}/stream
Accept: text/event-stream
```

### SSE Event Types

```python
class SSEEventType(str, Enum):
    MESSAGE = "message"              # New message created
    MESSAGE_UPDATE = "message_update" # Message status/content updated
    ARTIFACT = "artifact"            # Data artifact available (query result chunk)
    STATUS = "status"                # Status update (processing, etc.)
    ERROR = "error"                  # Error occurred
    PING = "ping"                    # Keep-alive heartbeat
    DONE = "done"                    # Processing complete
```

### SSE Event Format

```typescript
// SSE event structure
interface SSEEvent {
  event: SSEEventType;
  id?: string;      // Event ID for tracking
  data: string;     // JSON-encoded payload
  retry?: number;   // Reconnection time in ms
}

// Event payloads
interface MessageEvent {
  message: Message;  // Complete message object
}

interface MessageUpdateEvent {
  message_id: string;
  updates: Partial<Message>;  // Only changed fields
}

interface ArtifactEvent {
  message_id: string;
  artifact_type: "query_result" | "plan_step" | "table_chunk";
  data: any;  // Actual artifact data
  metadata?: Record<string, any>;
}

interface StatusEvent {
  message_id?: string;
  status: MessageStatus;
  progress?: number;  // 0-100
  description?: string;
}
```

### Backend Implementation

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

@app.get("/api/v2/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request):
    """
    SSE endpoint for streaming messages and artifacts in real-time
    """
    
    async def event_generator():
        """Generate SSE events as messages are created"""
        
        # Subscribe to session message queue (Redis, in-memory, etc.)
        queue = await get_session_queue(session_id)
        
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                # Wait for next event (with timeout for heartbeat)
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    
                    # Send event to client
                    yield {
                        "event": event.type,
                        "id": event.id,
                        "data": json.dumps(event.payload),
                        "retry": 5000
                    }
                    
                except asyncio.TimeoutError:
                    # Send heartbeat ping
                    yield {
                        "event": "ping",
                        "data": json.dumps({"timestamp": datetime.utcnow().isoformat()})
                    }
                
        finally:
            # Cleanup on disconnect
            await cleanup_session_queue(session_id, queue)
    
    return EventSourceResponse(event_generator())


# VersatileFlow publishes events during execution
class VersatileFlow:
    async def handle_chat_message(self, message: Message) -> List[Message]:
        """Enhanced with SSE event publishing"""
        
        queue = await get_session_queue(message.session_id)
        
        # Publish transient status update (not stored in DB)
        status_msg = Message.create_notification(
            text="Analyzing your request...",
            role=MessageRole.SYSTEM,
            session_id=message.session_id
        )
        await queue.publish({
            "type": "status",
            "id": status_msg.id,
            "payload": {
                "status": "processing",
                "description": status_msg.text
            }
        })
        # Note: status_msg.persistent = False, so not saved to DB
        
        # Create execution plan
        plan = await self.create_execution_plan(message.text)
        
        # Publish plan message
        plan_message = Message(
            content=plan.model_dump(),
            kind=MessageKind.EXECUTION_PLAN,
            ...
        )
        await save_message(plan_message)
        
        await queue.publish({
            "type": "message",
            "id": plan_message.id,
            "payload": {"message": plan_message.model_dump()}
        })
        
        # Execute steps, publishing artifacts as they complete
        for step in plan.steps:
            # Publish step start
            await queue.publish({
                "type": "status",
                "payload": {
                    "status": "processing",
                    "description": f"Step {step.step_number}: {step.description}",
                    "progress": (step.step_number / len(plan.steps)) * 100
                }
            })
            
            # Execute step
            result = await self.execute_step(step)
            
            # Publish artifact immediately
            await queue.publish({
                "type": "artifact",
                "id": str(uuid4()),
                "payload": {
                    "message_id": plan_message.id,
                    "artifact_type": "plan_step",
                    "data": {
                        "step_id": step.step_id,
                        "status": "completed",
                        "result_summary": result.summary,
                        "row_count": result.row_count
                    }
                }
            })
        
        # Publish final result
        final_message = Message(
            content={...},
            kind=MessageKind.QUERY_RESULT,
            ...
        )
        await save_message(final_message)
        
        await queue.publish({
            "type": "message",
            "id": final_message.id,
            "payload": {"message": final_message.model_dump()}
        })
        
        # Signal completion
        await queue.publish({
            "type": "done",
            "payload": {"session_id": message.session_id}
        })
        
        return [plan_message, final_message]
```

### Frontend Integration

```typescript
// SSE client hook
function useSessionStream(sessionId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<string>('idle');
  const [progress, setProgress] = useState<number>(0);
  
  useEffect(() => {
    const eventSource = new EventSource(
      `/api/v2/sessions/${sessionId}/stream`
    );
    
    // New message received
    eventSource.addEventListener('message', (e) => {
      const data = JSON.parse(e.data) as MessageEvent;
      setMessages(prev => [...prev, data.message]);
    });
    
    // Message updated (e.g., status change)
    eventSource.addEventListener('message_update', (e) => {
      const data = JSON.parse(e.data) as MessageUpdateEvent;
      setMessages(prev => prev.map(msg => 
        msg.id === data.message_id 
          ? { ...msg, ...data.updates }
          : msg
      ));
    });
    
    // Artifact received (query result chunk, step completion, etc.)
    eventSource.addEventListener('artifact', (e) => {
      const data = JSON.parse(e.data) as ArtifactEvent;
      
      // Update message with artifact data
      setMessages(prev => prev.map(msg => 
        msg.id === data.message_id
          ? {
              ...msg,
              metadata: {
                ...msg.metadata,
                artifacts: [
                  ...(msg.metadata.artifacts || []),
                  data
                ]
              }
            }
          : msg
      ));
    });
    
    // Status update
    eventSource.addEventListener('status', (e) => {
      const data = JSON.parse(e.data) as StatusEvent;
      setStatus(data.description || data.status);
      if (data.progress !== undefined) {
        setProgress(data.progress);
      }
    });
    
    // Error handling
    eventSource.addEventListener('error', (e) => {
      console.error('SSE error:', e);
      if (eventSource.readyState === EventSource.CLOSED) {
        // Reconnect logic handled by browser
      }
    });
    
    // Processing complete
    eventSource.addEventListener('done', () => {
      setStatus('completed');
      setProgress(100);
    });
    
    return () => {
      eventSource.close();
    };
  }, [sessionId]);
  
  return { messages, status, progress };
}

// Usage in component
function ChatContainer({ sessionId }: { sessionId: string }) {
  const { messages, status, progress } = useSessionStream(sessionId);
  
  return (
    <>
      {status === 'processing' && (
        <LinearProgress variant="determinate" value={progress} />
      )}
      
      {messages.map(msg => (
        <MessageRenderer key={msg.id} message={msg} />
      ))}
      
      {status === 'processing' && (
        <Typography color="textSecondary">{status}</Typography>
      )}
    </>
  );
}
```

### Streaming Query Results (Large Datasets)

For large query results, stream data in chunks:

```python
# Backend: Stream query result in chunks
async def stream_query_result(query_id: str, session_id: str):
    queue = await get_session_queue(session_id)
    
    # Create message for query result
    msg = Message(
        content={
            "query_id": query_id,
            "row_count": None,  # Unknown yet
            "strategy": "stream",
            "columns": [...]
        },
        kind=MessageKind.QUERY_RESULT,
        status=MessageStatus.PROCESSING
    )
    await save_message(msg)
    
    # Publish initial message
    await queue.publish({
        "type": "message",
        "payload": {"message": msg.model_dump()}
    })
    
    # Stream results in chunks
    chunk_size = 1000
    total_rows = 0
    
    async for chunk in execute_query_chunked(query_id, chunk_size):
        total_rows += len(chunk)
        
        # Publish chunk as artifact
        await queue.publish({
            "type": "artifact",
            "payload": {
                "message_id": msg.id,
                "artifact_type": "table_chunk",
                "data": {
                    "rows": chunk,
                    "offset": total_rows - len(chunk),
                    "chunk_size": len(chunk)
                },
                "metadata": {
                    "total_rows_so_far": total_rows
                }
            }
        })
    
    # Update message with final count
    msg.status = MessageStatus.COMPLETED
    msg.content["row_count"] = total_rows
    await update_message(msg)
    
    await queue.publish({
        "type": "message_update",
        "payload": {
            "message_id": msg.id,
            "updates": {
                "status": "completed",
                "content": msg.content
            }
        }
    })

# Frontend: Accumulate chunks as they arrive
function StreamingDataGrid({ message }: { message: Message }) {
  const [rows, setRows] = useState<any[]>([]);
  const [totalRows, setTotalRows] = useState<number | null>(null);
  
  useEffect(() => {
    // Listen for artifacts on this message
    const artifacts = message.metadata.artifacts || [];
    
    artifacts.forEach(artifact => {
      if (artifact.artifact_type === 'table_chunk') {
        // Append chunk to existing rows
        setRows(prev => [...prev, ...artifact.data.rows]);
        setTotalRows(artifact.metadata.total_rows_so_far);
      }
    });
  }, [message.metadata.artifacts]);
  
  return (
    <Box>
      <MUIDataGrid 
        rows={rows} 
        columns={message.content.columns}
        loading={message.status === 'processing'}
      />
      {message.status === 'processing' && totalRows && (
        <Typography variant="caption">
          Loaded {rows.length.toLocaleString()} of {totalRows.toLocaleString()} rows...
        </Typography>
      )}
    </Box>
  );
}
```

### SSE with Agentic Flows

Execution plans benefit from SSE streaming:

```
User sends message
    ↓
SSE: status → "Analyzing request..."
SSE: message → EXECUTION_PLAN
    [User reviews plan in UI]
User approves plan
    ↓
SSE: status → "Step 1/4: Identifying wallets..."
SSE: artifact → step_1_start
SSE: status → progress: 25%
SSE: artifact → step_1_result (487 wallets)
SSE: message → PLAN_STEP (step 1 complete)
    ↓
SSE: status → "Step 2/4: Analyzing token preferences..."
SSE: artifact → step_2_start
SSE: status → progress: 50%
SSE: message → CLARIFICATION (include meme tokens?)
    [User responds]
SSE: artifact → step_2_result
SSE: message → PLAN_STEP (step 2 complete)
    ↓
SSE: status → "Step 3/4: Calculating similarity..."
SSE: status → progress: 75%
SSE: artifact → step_3_result
    ↓
SSE: status → "Step 4/4: Generating graph..."
SSE: status → progress: 100%
SSE: artifact → final_result
SSE: message → QUERY_RESULT
SSE: done
```

### Infrastructure

```python
# Message queue (Redis example)
import redis.asyncio as redis
import json

class SessionQueue:
    """Redis-backed queue for SSE events"""
    
    def __init__(self, session_id: str, redis_client: redis.Redis):
        self.session_id = session_id
        self.redis = redis_client
        self.channel = f"session:{session_id}:events"
    
    async def publish(self, event: dict):
        """Publish event to session stream"""
        await self.redis.publish(
            self.channel,
            json.dumps(event)
        )
    
    async def subscribe(self):
        """Subscribe to session events (for SSE endpoint)"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel)
        return pubsub
    
    async def get(self, timeout: float = None) -> dict:
        """Get next event from queue"""
        # Implementation depends on queue backend
        pass

# Celery task publishes events
@celery_app.task
def versatile_flow_task(session_id: str, message_dict: dict):
    queue = SessionQueue(session_id, redis_client)
    
    # All flow operations publish to queue
    flow = VersatileFlow(queue=queue)
    flow.process_message(Message(**message_dict))
```

### Benefits

✅ **Real-time feedback** - Users see progress immediately  
✅ **No timeout issues** - Long operations don't timeout, stream continuously  
✅ **Progressive data delivery** - Large results appear as they're computed  
✅ **Better UX** - No more "Loading..." spinners, actual progress shown  
✅ **Multiple responses** - Single request → multiple messages naturally  
✅ **Automatic reconnection** - Browser handles disconnect/reconnect  
✅ **Standard protocol** - SSE is native to browsers, no WebSocket complexity  
✅ **Artifact streaming** - Query results, plan steps, charts stream incrementally  

## Frontend Integration

### TypeScript Types

```typescript
// New v2 types
export enum MessageRole {
  USER = "user",
  ASSISTANT = "assistant",
  SYSTEM = "system",
  TOOL = "tool",
  COMMAND = "command",
}

export enum MessageKind {
  CHAT = "chat",
  SLASH_COMMAND = "slash_command",
  TOOL_RESULT = "tool_result",
  NOTIFICATION = "notification",
  DEBUG = "debug",
  QUERY_RESULT = "query_result",
  CHART = "chart",
  TABLE = "table",
}

export enum MessageStatus {
  PENDING = "pending",
  PROCESSING = "processing",
  COMPLETED = "completed",
  FAILED = "failed",
  CANCELLED = "cancelled",
}

export interface Message {
  id: string;
  session_id: string;
  
  // Content
  content: string;
  content_type: string;
  
  // Classification
  role: MessageRole;
  kind: MessageKind;
  
  // Metadata
  created_at: string;
  metadata: Record<string, any>;
  
  // Relationships
  parent_id?: string;
  thread_id?: string;
  tags: string[];
  
  // Status
  status: MessageStatus;
  error?: string;
}

export interface SessionV2 {
  session_id: string;
  created_at: string;
  messages: Message[];
}
```

### UI Rendering Logic

```typescript
// Group messages into threads for display
function groupMessagesIntoThreads(messages: Message[]): MessageThread[] {
  const threads = new Map<string, Message[]>();
  
  for (const msg of messages) {
    const threadKey = msg.thread_id || msg.parent_id || msg.id;
    if (!threads.has(threadKey)) {
      threads.set(threadKey, []);
    }
    threads.get(threadKey)!.push(msg);
  }
  
  return Array.from(threads.values()).map(msgs => ({
    id: msgs[0].thread_id || msgs[0].id,
    messages: msgs.sort((a, b) => 
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )
  }));
}

// Render message based on kind
function renderMessage(message: Message) {
  switch (message.kind) {
    case MessageKind.CHAT:
      return <ResponseTextMessage text={message.content} />;
    
    case MessageKind.QUERY_RESULT:
      return (
        <>
          <ResponseTextMessage text={message.content} />
          <QueryResultTable metadata={message.metadata} />
        </>
      );
    
    case MessageKind.TOOL_RESULT:
      // Hidden by default, show in debug mode
      return <ToolResultDebug message={message} collapsed />;
    
    case MessageKind.NOTIFICATION:
      return <NotificationBanner message={message} />;
    
    case MessageKind.CHART:
      return <ChartVisualization data={message.metadata} />;
    
    default:
      return <div>{message.content}</div>;
  }
}

// Filter messages for display
function filterVisibleMessages(messages: Message[], showDebug: boolean = false) {
  return messages.filter(msg => {
    // Always hide command messages
    if (msg.role === MessageRole.COMMAND) return false;
    
    // Hide tool results and debug unless debug mode enabled
    if (!showDebug && (
      msg.kind === MessageKind.TOOL_RESULT ||
      msg.kind === MessageKind.DEBUG
    )) {
      return false;
    }
    
    return true;
  });
}
```

## Migration Strategy

### Phase 1: Schema & API (v2 foundation)

1. Create new database tables (`messages`, `message_queries`, `message_attachments`)
2. Implement v2 API endpoints (`/api/v2/sessions`, `/api/v2/messages`)
3. Implement VersatileFlow handler
4. Keep v1 API and InteractiveFlow completely unchanged

### Phase 2: Feature Parity

1. Implement slash commands (`/new`, `/help`) in VersatileFlow
2. Implement basic chat query flow (user question → SQL → results)
3. Test v2 API with simple queries

### Phase 3: Frontend Support

1. Add v2 TypeScript types
2. Create feature flag for v2 UI
3. Implement message-based chat UI (alongside existing v1 UI)
4. Add support for multiple responses per request

### Phase 4: Advanced Features

1. Multimodal support (images, charts in messages)
2. Streaming responses (WebSocket)
3. Message threading/grouping UI
4. Debug mode (show tool results)

### Phase 5: Gradual Migration

1. New sessions use v2 by default (opt-in)
2. Monitor usage and stability
3. Eventually deprecate v1 (long-term)

## Tabular Data Distribution

### Overview

Since the primary use case is data exploration and transformation, we need an efficient strategy for distributing query results. The approach adapts based on result size, leveraging existing v1 models where possible.

### Supported MIME Types

```python
class DataMimeType(str, Enum):
    # Text formats
    TEXT_MARKDOWN = "text/markdown"
    TEXT_CSV = "text/csv"
    
    # JSON formats
    JSON = "application/json"
    NDJSON = "application/x-ndjson"  # For streaming
    
    # Binary/Columnar formats (efficient storage/transfer)
    PARQUET = "application/vnd.apache.parquet"  # IANA registered
    ARROW_STREAM = "application/vnd.apache.arrow.stream"  # IANA registered
    
    # Custom table format (wraps existing v1 structures)
    TABLE_JSON = "application/vnd.semanticgrid.table+json"
```

### Distribution Strategy (Size-Based)

| Rows | Strategy | Storage | Access Pattern |
|------|----------|---------|----------------|
| < 100 | **Embedded** | JSON in `content` | Direct display |
| 100 - 10K | **Paginated** | URL to paginated API | Fetch pages on scroll |
| 10K - 1M | **Download** | Parquet/CSV on S3 | Download or lazy load |
| > 1M | **Stream** | Query on-demand | WebSocket/SSE stream |

### Query Result Content Model

```python
# Reuses existing v1 models
from fm_app.api.model import Column, QueryMetadata, Refs, View

class QueryResultContent(BaseModel):
    """
    Content structure for query results in v2 messages.
    Reuses existing v1 Column, QueryMetadata, Refs, View models.
    """
    
    # Core metadata (reuse existing)
    columns: List[Column]  # Existing v1 Column model
    row_count: int
    query_id: Optional[UUID] = None
    
    # Distribution strategy
    strategy: Literal["embedded", "paginated", "download", "stream"]
    
    # Data access
    preview: Optional[List[Dict[str, Any]]] = None  # First 50-100 rows (always JSON)
    embedded_data: Optional[List[Dict[str, Any]]] = None  # For <100 rows (complete data)
    
    # URLs for larger data
    paginated_url: Optional[str] = None  # /api/v2/data/{query_id}?page=1&size=100
    download_url: Optional[str] = None   # S3 URL (Parquet/CSV)
    stream_url: Optional[str] = None     # WebSocket/SSE endpoint
    
    # Available download formats
    available_formats: List[DataMimeType] = Field(default_factory=lambda: [
        DataMimeType.JSON,
        DataMimeType.CSV,
        DataMimeType.PARQUET
    ])
    
    # Backward compatibility with v1
    refs: Optional[Refs] = None
    view: Optional[View] = None
```

### Strategy Selection Logic

```python
def determine_strategy(row_count: int) -> str:
    """Auto-select distribution strategy based on result size"""
    if row_count < 100:
        return "embedded"      # Include all data in message
    elif row_count < 10_000:
        return "paginated"     # Use pagination API
    elif row_count < 1_000_000:
        return "download"      # Offer Parquet/CSV download
    else:
        return "stream"        # WebSocket streaming (future)
```

### Example Messages

#### Small Result (Embedded)
```python
msg = Message(
    content={
        "columns": [
            {"id": "wallet", "column_name": "wallet", "column_type": "string"},
            {"id": "volume", "column_name": "volume", "column_type": "number"}
        ],
        "row_count": 10,
        "strategy": "embedded",
        "embedded_data": [
            {"wallet": "0x123...", "volume": 1000000},
            {"wallet": "0x456...", "volume": 500000},
            # ... 10 rows total
        ]
    },
    content_type=DataMimeType.TABLE_JSON,
    kind=MessageKind.QUERY_RESULT,
    metadata={"query_id": "q_123", "sql": "SELECT ..."}
)
```

#### Medium Result (Paginated)
```python
msg = Message(
    content={
        "columns": [...],
        "row_count": 5000,
        "strategy": "paginated",
        "preview": [...],  # First 100 rows
        "paginated_url": "/api/v2/data/q_123",
        "available_formats": ["json", "csv", "parquet"]
    },
    content_type=DataMimeType.TABLE_JSON,
    kind=MessageKind.QUERY_RESULT,
    metadata={"query_id": "q_123"}
)
```

#### Large Result (Download)
```python
msg = Message(
    content={
        "columns": [...],
        "row_count": 1_000_000,
        "strategy": "download",
        "preview": [...],  # First 100 rows
        "download_url": "s3://bucket/results/q_123.parquet",
        "available_formats": ["parquet", "csv", "json"]
    },
    content_type=DataMimeType.TABLE_JSON,
    kind=MessageKind.QUERY_RESULT,
    metadata={
        "query_id": "q_123",
        "file_size_bytes": 50_000_000
    }
)
```

### Data Access API Endpoints

```python
# Paginated data access (reuses v1 GetDataRequest/GetDataResponse pattern)
GET /api/v2/data/{query_id}?page=1&size=100&format=json
GET /api/v2/data/{query_id}?page=1&size=100&format=csv

# Download full dataset
GET /api/v2/data/{query_id}/download?format=parquet
GET /api/v2/data/{query_id}/download?format=csv

# Response headers include proper MIME type
Content-Type: application/json
Content-Type: text/csv
Content-Type: application/vnd.apache.parquet
```

### Frontend Integration

```typescript
// Reuses existing MUI Data Grid Pro
function DataGrid({ message }: { message: Message }) {
  const resultData = message.content as QueryResultContent;
  
  if (resultData.strategy === 'embedded') {
    // Render all data directly
    return <MUIDataGrid rows={resultData.embedded_data} columns={...} />;
  }
  
  if (resultData.strategy === 'paginated') {
    // Use MUI Data Grid with server-side pagination
    return (
      <MUIDataGrid
        pagination
        paginationMode="server"
        rowCount={resultData.row_count}
        onPaginationModelChange={(model) => {
          fetch(`${resultData.paginated_url}?page=${model.page}&size=${model.pageSize}`)
            .then(r => r.json())
            .then(data => setRows(data.rows));
        }}
      />
    );
  }
  
  if (resultData.strategy === 'download') {
    // Show preview + download button
    return (
      <>
        <MUIDataGrid rows={resultData.preview} columns={...} />
        <DownloadButton 
          url={resultData.download_url}
          formats={resultData.available_formats}
          rowCount={resultData.row_count}
        />
      </>
    );
  }
}
```

### Benefits

✅ **Reuses existing v1 models** - Column, QueryMetadata, Refs, View  
✅ **Size-adaptive** - Strategy automatically selected based on row count  
✅ **Multiple formats** - JSON (UI), CSV (Excel), Parquet (efficient)  
✅ **Standards-compliant** - Uses IANA-registered MIME types (Parquet, Arrow)  
✅ **Preview always available** - First N rows for immediate display  
✅ **Backward compatible** - Works with existing MUI Data Grid Pro  
✅ **Scalable** - Handles 10 rows to 10M rows efficiently  

## Decisions Made

### 1. Session Versioning
**Decision**: Add `api_version` column to `sessions` table with values `'v1'` or `'v2'`. Backfill existing sessions as `'v1'` during migration.

**Rationale**: Clean separation between v1 (request-response) and v2 (messages) without breaking existing sessions.

### 2. Content Storage Strategy
**Decision**: Use JSONB for `messages.content` field (stores text, JSON, or references). Binary data goes in `message_attachments` table with either S3 URLs or inline BYTEA (<1MB).

**Rationale**: 
- Single field in DB (clean schema)
- Type-safe getters in Python (`.text`, `.data`, `.binary_url`)
- Efficient for text/JSON (indexed, queryable)
- Separate storage for binary (no bloat)

### 3. Tabular Data Distribution
**Decision**: Use hybrid approach with size-based strategy selection:
- <100 rows: Embed in message
- 100-10K: Paginated API
- 10K-1M: S3 download (Parquet/CSV)
- >1M: Streaming (future)

**Rationale**: Balances performance, UX, and infrastructure costs. Always includes preview for instant rendering.

### 4. MIME Types
**Decision**: Support standard IANA-registered types (Parquet, Arrow) plus custom `application/vnd.semanticgrid.table+json` for our table format.

**Rationale**: Standards-compliant, interoperable with data science tools, future-proof.

### 5. Visualization Support
**Decision**: Defer visualization MIME types (Vega, Plotly) to later phase. Focus on tabular data distribution first. Frontend handles visualization via existing JS/TS libraries.

**Rationale**: Core use case is data exploration. Visualization can be layered on top once data distribution is solid.

### 6. Agentic Flows Support
**Decision**: Native support for multi-step execution plans with:
- New message kinds: `execution_plan`, `plan_approval`, `plan_step`, `clarification`, `clarification_response`
- Execution plan model with steps, dependencies, complexity assessment
- Auto/manual execution modes (user preference)
- Mid-execution clarifications and user decisions
- Progress tracking via `plan_step` messages

**Rationale**: Complex queries often require multiple steps (data fetch → analysis → transformation). Users need visibility and control over what will execute. Agentic flows enable transparent, interactive multi-step workflows while maintaining full audit trail in message history.

### 7. Real-Time Streaming (SSE)
**Decision**: Use Server-Sent Events (SSE) for real-time streaming of messages, status updates, and artifacts. Event types: `message`, `message_update`, `artifact`, `status`, `error`, `ping`, `done`.

**Rationale**: 
- Long-running queries need progress feedback without timeout
- Agentic flows benefit from real-time step updates
- Large datasets can stream incrementally (table chunks)
- SSE is simpler than WebSocket, browser-native, auto-reconnects
- Enables "multiple responses per request" pattern naturally
- Better UX: progressive feedback vs loading spinners

### 8. LLM Provider Compatibility
**Decision**: Message roles map cleanly to OpenAI (`user`, `assistant`, `system`, `tool`), Anthropic (`user`, `assistant`, tool as `user` with `tool_result`), and Gemini (`user`, `model`, `system`, `function`). Internal message kinds (execution_plan, plan_approval, etc.) filtered when building LLM context.

**Rationale**:
- Provider-agnostic storage allows switching LLMs without schema changes
- Rich message kinds (plan, clarification, etc.) enable features beyond basic chat
- Conversion functions map our schema to each provider's format
- Tool calling supported across all major providers
- System prompts adapt to provider-specific patterns (message vs parameter)
- Future-proof: add new providers without breaking existing data

### 9. Message Persistence
**Decision**: Add `persistent` boolean field to Message model. Transient messages (`persistent=False`) are streamed via SSE but not stored in DB. Applies to: notifications, plan_step progress updates, status messages, debug info.

**Rationale**:
- Reduces DB writes for ephemeral messages (progress updates, notifications)
- Better performance - less I/O for real-time updates
- Cleaner conversation history - only meaningful messages stored
- SSE streams all messages (persistent + transient) for real-time UX
- Persistent messages (chat, query_result, execution_plan, etc.) stored for audit/replay
- Flexible: debug messages can be persistent when debug mode enabled

## Open Questions & Decisions Needed

### Resolved

1. ✅ **message_metadata table**: Use JSONB in `messages.metadata`. No separate table needed.

2. ✅ **Content storage**: Single JSONB field for polymorphic content (text/JSON/references). Binary data in `message_attachments`.

3. ✅ **Session versioning**: Add `api_version` column to sessions table. Backfill existing as `v1`.

4. ✅ **Tabular data**: Size-based strategy (embedded/paginated/download/stream). Always include preview.

5. ✅ **MIME types**: Use IANA-registered types (Parquet, Arrow) + custom `application/vnd.semanticgrid.table+json`.

6. ✅ **Attachments storage**: Hybrid - S3 URLs for large files (preferred), inline BYTEA for <1MB, data URIs for <100KB.

7. ✅ **Visualization**: Defer to later phase. Frontend handles with JS/TS libraries.

8. ✅ **Streaming**: SSE for real-time message/artifact delivery. Event types: message, message_update, artifact, status, error, ping, done.

### Still Open

1. **Thread management**: Should `thread_id` be auto-generated or user-controlled? How do we decide when to create a new thread?
   - Proposal: Auto-generate `thread_id = parent_id or message_id` for simplicity. Frontend can override if needed.

3. **v1 to v2 migration**: Do we ever migrate existing v1 sessions/requests to v2 format, or keep them separate forever?
   - Proposal: Keep separate. v1 sessions stay v1 forever. Only new sessions can be v2.

4. **Message ordering**: Should we add explicit `order` or `sequence_number` field, or rely on `created_at`?
   - Proposal: Rely on `created_at` timestamp. Add `sequence_number` only if we see ordering issues.

5. **Tool result visibility**: Should tool results be visible by default or hidden? Per-user preference or global setting?
   - Proposal: Hidden by default, show in "debug mode" toggle (per-user preference in localStorage).

## Success Metrics

- v2 API handles all existing use cases (query generation, slash commands)
- No disruption to v1 API users
- Support for 1:N request:response patterns
- Clean separation of concerns (role vs kind)
- Frontend can render all message types
- Performance comparable to v1 (no regression)

## Next Steps

1. Review and finalize this architecture doc
2. Create database migration files (Alembic)
3. Implement v2 API models and endpoints
4. Implement VersatileFlow core logic
5. Create TypeScript types and minimal UI
6. Test with basic scenarios

---

## Document Summary

This architecture defines Semantic Grid v2, a message-based chat system that replaces the rigid request-response pattern with flexible, multi-response conversations.

### Key Highlights

- **Flat message structure** with role+kind taxonomy
- **Polymorphic content** (JSONB storage, Union types in Python)
- **Size-adaptive tabular data** distribution (embedded → paginated → download → stream)
- **IANA-registered MIME types** (Parquet, Arrow) for standards compliance
- **Reuses v1 models** (Column, QueryMetadata, Refs, View) for backward compatibility
- **Session versioning** (`api_version`) allows v1 and v2 to coexist
- **Binary/multimodal support** via attachments table (S3 URLs or inline)
- **Agentic execution flows** with multi-step plans, user approval, and mid-execution clarifications
- **Real-time SSE streaming** for progressive message/artifact delivery and status updates
- **LLM provider compatibility** - Clean mapping to OpenAI, Anthropic, Gemini APIs
- **Message persistence control** - Transient messages (notifications, progress) streamed but not stored

### Implementation Phases

1. **Phase 1**: Database schema + v2 API foundation
2. **Phase 2**: Feature parity (slash commands, basic queries)
3. **Phase 3**: Frontend support (message-based UI)
4. **Phase 4**: Advanced features (streaming, multimodal)
5. **Phase 5**: Gradual migration (v2 becomes default)

### Next Steps

1. ✅ Finalize architecture document (this document)
2. Create Alembic migrations for v2 schema
3. Implement v2 API models and Pydantic classes
4. Implement VersatileFlow handler
5. Create TypeScript types for frontend
6. Build minimal v2 UI for testing

---

**Document Version**: 0.2 (Updated with decisions)  
**Last Updated**: 2025-01-08  
**Authors**: System Architecture Team  
**Status**: Ready for implementation
