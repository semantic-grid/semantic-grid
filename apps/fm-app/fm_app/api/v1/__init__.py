"""
API v1 - Legacy request-response architecture.

This version uses:
- Session-level QueryMetadata (mutable, progressively updated)
- Request-level Query artifacts (immutable)
- 1:1 request-response pairs
"""

# Only export models, not routes (to avoid circular imports)
# Routes should be imported directly: from fm_app.api.v1.routes import api_router
from fm_app.api.v1.model import (
    AddLinkedRequestModel,
    AddRequestModel,
    ChartRequest,
    ChartStructuredRequest,
    ChartType,
    Column,
    CreateQueryFromSqlModel,
    CreateQueryModel,
    CreateSessionModel,
    DBType,
    FlowType,
    GetDataResponse,
    GetPromptModel,
    GetQueryModel,
    GetRequestModel,
    GetSessionModel,
    IntentAnalysis,
    InteractiveRequestType,
    McpServerRequest,
    ModelType,
    PatchSessionModel,
    PromptItem,
    PromptItemType,
    PromptsSetModel,
    QueryMetadata,
    Refs,
    RequestStatus,
    StructuredResponse,
    UpdateQueryMetadataModel,
    UpdateQueryModel,
    UpdateRequestModel,
    UpdateRequestStatusModel,
    Version,
    View,
    WorkerRequest,
)

__all__ = [
    # Enums
    "RequestStatus",
    "InteractiveRequestType",
    "FlowType",
    "ModelType",
    "DBType",
    "Version",
    "ChartType",
    "PromptItemType",
    # Models
    "Refs",
    "Column",
    "View",
    "QueryMetadata",
    "StructuredResponse",
    "IntentAnalysis",
    "GetPromptModel",
    "PromptItem",
    "PromptsSetModel",
    "ChartRequest",
    "ChartStructuredRequest",
    "McpServerRequest",
    # Session Models
    "CreateSessionModel",
    "GetSessionModel",
    "PatchSessionModel",
    "UpdateQueryMetadataModel",
    # Query Models
    "CreateQueryModel",
    "CreateQueryFromSqlModel",
    "UpdateQueryModel",
    "GetQueryModel",
    # Request Models
    "GetRequestModel",
    "UpdateRequestStatusModel",
    "AddRequestModel",
    "AddLinkedRequestModel",
    "UpdateRequestModel",
    "GetDataResponse",
    # Worker Models
    "WorkerRequest",
]
