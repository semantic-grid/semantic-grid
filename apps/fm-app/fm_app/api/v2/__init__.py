"""
API v2 - Flexible message-based architecture.

This version uses:
- Message-level message_queries (immutable)
- Flexible message taxonomy (role + kind)
- Support for multi-response, slash commands, agentic flows
- SSE streaming for real-time updates
"""

from fm_app.api.v2.model import (
    PERSISTENCE_RULES,
    CreateSessionRequest,
    CreateSessionResponse,
    GetMessagesResponse,
    GetSessionResponse,
    Message,
    MessageAttachment,
    MessageKind,
    MessageQuery,
    MessageRole,
    MessageStatus,
    SendMessageRequest,
    SendMessageResponse,
)
from fm_app.api.v2.routes import api_router_v2

__all__ = [
    # Enums
    "MessageRole",
    "MessageKind",
    "MessageStatus",
    # Core Models
    "Message",
    "MessageAttachment",
    "MessageQuery",
    # Request/Response Models
    "CreateSessionRequest",
    "CreateSessionResponse",
    "SendMessageRequest",
    "SendMessageResponse",
    "GetSessionResponse",
    "GetMessagesResponse",
    # Constants
    "PERSISTENCE_RULES",
    # Router
    "api_router_v2",
]
