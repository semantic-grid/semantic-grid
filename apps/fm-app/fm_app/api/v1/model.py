from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict

### General Models


class Refs(BaseModel):
    parent: Optional[UUID] = None
    steps: Optional[list[UUID]] = None
    cols: Optional[list[str]] = None
    rows: Optional[list[list[Union[str, int, float]]]] = None


class RequestStatus(str, Enum):
    new = "New"
    intent = "Intent"
    sql = "SQL"
    data = "DataFetch"
    retry = "Retry"
    finalizing = "Finalizing"
    in_process = "InProgress"
    scheduled = "Scheduled"
    error = "Error"
    done = "Done"
    cancelled = "Cancelled"


class InteractiveRequestType(str, Enum):
    tbd = "tbd"
    interactive_query = "interactive_query"
    data_analysis = "data_analysis"
    general_chat = "general_chat"
    disambiguation = "disambiguation"
    linked_session = "linked_session"
    linked_query = "linked_query"
    manual_query = "manual_query"
    discovery = "discovery"
    # chart_request = "chart_request"


class FlowType(str, Enum):
    # legacy flows - simple
    openai_simple = "OpenAISimple"
    openai_simple_new_wh = "OpenAISimpleNWH"
    openai_simple_v2 = "OpenAISimpleV2"
    gemini_simple = "GeminiSimple"
    gemini_simple_new_wh = "GeminiSimpleNWH"
    gemini_simple_v2 = "GeminiSimpleV2"
    deepseek_simple = "DeepseekSimple"
    deepseek_simple_new_wh = "DeepseekSimpleNWH"
    deepseek_simple_v2 = "DeepseekSimpleV2"
    anthropic_simple = "AnthropicSimple"
    anthropic_simple_new_wh = "AnthropicSimpleNWH"
    anthropic_simple_v2 = "AnthropicSimpleV2"
    # legacy flows - multistep
    openai_multisteps = "OpenAIMultisteps"
    openai_multistep = "OpenAIMultistep"
    gemini_multistep = "GeminiMultistep"
    deepseek_multistep = "DeepseekMultistep"
    anthropic_multistep = "AnthropicMultistep"
    # new flows
    simple = "Simple"
    multistep = "Multistep"
    data_only = "DataOnly"
    mcp = "MCP"
    flex = "Flex"
    langgraph = "LangGraph"
    interactive = "Interactive"


class ModelType(str, Enum):
    openai_default = "OpenAI"
    gemini_default = "Gemini"
    deepseek_default = "Deepseek"
    anthropic_default = "Anthropic"


class DBType(str, Enum):
    legacy = ""
    new_wh = "NWH"
    v2 = "V2"


class Version(int, Enum):
    static = 1
    interactive = 2


class Column(BaseModel):
    id: str = None
    summary: Optional[str] = None
    column_name: Optional[str] = None
    column_alias: Optional[str] = None
    column_type: Optional[str] = None
    column_description: Optional[str] = None


class View(BaseModel):
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None


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


class StructuredResponse(BaseModel):
    intent: Optional[str] = None
    assumptions: Optional[str] = None
    sql: Optional[str] = None
    intro: Optional[str] = None
    outro: Optional[str] = None
    raw_data_labels: Optional[list[str]] = None
    raw_data_rows: Optional[list[list[Union[str, int, float]]]] = None
    csv: Optional[str] = None
    chart: Optional[str] = None
    chart_url: Optional[str] = None
    metadata: Optional[QueryMetadata] = None
    refs: Optional[Refs] = None
    linked_session_id: Optional[UUID] = None
    description: Optional[str] = None


class IntentAnalysis(BaseModel):
    request_type: InteractiveRequestType = InteractiveRequestType.interactive_query
    intent: Optional[str] = None
    response: Optional[str] = None


class PromptItemType(str, Enum):
    db_struct = "DBStruct"
    query_example = "QueryExample"
    data_description = "DataDescription"
    ref_sources = "RefSources"
    instruction = "Instruction"
    data_sample = "DataSample"
    slot_schema = "SlotSchema"


class GetPromptModel(BaseModel):
    user_request: str
    db: str | None = None


class PromptItem(BaseModel):
    text: str
    prompt_item_type: PromptItemType
    score: int


class PromptsSetModel(BaseModel):
    prompt_items: list[PromptItem]
    source: str


class ChartRequest(BaseModel):
    code: str


class ChartType(str, Enum):
    pie = "Pie"
    bar = "Bar"


class ChartStructuredRequest(BaseModel):
    chart_type: ChartType
    labels: list[str]
    rows: list[list[Any]]


### Session Models


class CreateSessionModel(BaseModel):
    name: Optional[str] = None
    tags: Optional[str] = None
    parent: Optional[UUID] = None
    refs: Optional[Refs] = None


class GetSessionModel(BaseModel):
    user: str
    session_id: UUID
    created_at: datetime
    name: Optional[str] = None
    tags: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    parent: Optional[UUID] = None
    refs: Optional[Refs] = None
    message_count: Optional[int] = None


class PatchSessionModel(BaseModel):
    name: Optional[str] = None
    tags: Optional[str] = None


class UpdateQueryMetadataModel(BaseModel):
    session_id: Optional[UUID] = None
    user: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


### Query Models


class CreateQueryModel(BaseModel):
    request: str
    intent: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    sql: Optional[str] = None
    row_count: Optional[int] = None
    columns: Optional[list[Column]] = None
    ai_generated: bool = True
    ai_context: Optional[dict[str, Any]] = None
    data_source: Optional[str] = None
    db_dialect: Optional[str] = None
    explanation: Optional[dict[str, Any]] = None
    parent_id: Optional[UUID] = None
    err: Optional[str] = None


class CreateQueryFromSqlModel(BaseModel):
    request: str
    sql: str = None
    ai_generated: bool = False
    ai_context: Optional[dict[str, Any]] = None
    data_source: Optional[str] = None
    db_dialect: Optional[str] = None


class UpdateQueryModel(BaseModel):
    query_id: UUID
    row_count: Optional[int] = None
    explanation: Optional[dict[str, Any]] = None
    err: Optional[str] = None


class GetQueryModel(CreateQueryModel):
    query_id: UUID


### Request Models


class GetRequestModel(BaseModel):
    session_id: UUID
    request_id: UUID
    sequence_number: int
    created_at: datetime
    request: str
    response: Optional[str] = None
    sql: Optional[str] = None
    rating: Optional[int] = None
    review: Optional[str] = None
    status: RequestStatus
    # new fields for structured response
    intent: Optional[str] = None
    assumptions: Optional[str] = None
    intro: Optional[str] = None
    outro: Optional[str] = None
    raw_data_labels: Optional[list[str]] = None
    raw_data_rows: Optional[list[list[Union[str, int, float]]]] = None
    csv: Optional[str] = None
    chart: Optional[str] = None
    chart_url: Optional[str] = None
    err: Optional[str] = None
    preset: Optional[str] = None
    session: Optional[GetSessionModel] = None
    refs: Optional[Refs] = None
    linked_session_id: Optional[UUID] = None
    query: Optional[GetQueryModel] = None
    view: Optional[View] = None


class UpdateRequestStatusModel(BaseModel):
    review: Optional[str]
    rating: Optional[int]
    status: Optional[RequestStatus]


class AddRequestModel(BaseModel):
    version: Version = Version.static
    request: str
    request_type: Optional[InteractiveRequestType] = InteractiveRequestType.tbd
    flow: Optional[FlowType] = FlowType.multistep
    model: Optional[ModelType] = ModelType.openai_default
    db: Optional[DBType] = DBType.legacy
    refs: Optional[Refs] = None
    query_id: Optional[UUID] = None


class AddLinkedRequestModel(BaseModel):
    # used for session
    name: Optional[str] = None
    tags: Optional[str] = None
    # used for request
    version: Version = Version.interactive
    request: str
    flow: Optional[FlowType] = FlowType.multistep
    model: Optional[ModelType] = ModelType.openai_default
    db: Optional[DBType] = DBType.legacy
    refs: Optional[Refs] = None


class UpdateRequestModel(BaseModel):
    request_id: UUID
    status: Optional[RequestStatus] = None
    err: Optional[str] = None
    response: Optional[str] = None
    sql: Optional[str] = None
    intent: Optional[str] = None
    assumptions: Optional[str] = None
    intro: Optional[str] = None
    outro: Optional[str] = None
    raw_data_labels: Optional[list[str]] = None
    raw_data_rows: Optional[list[list[Union[str, int, float]]]] = None
    csv: Optional[str] = None
    chart: Optional[str] = None
    chart_url: Optional[str] = None
    refs: Optional[dict[str, Any]] = None
    linked_session_id: Optional[UUID] = None
    query_id: Optional[UUID] = None
    view: Optional[View] = None


## Data Query Models


class GetDataRequest(BaseModel):
    query_id: UUID
    limit: int = 100
    offset: int = 0
    sort_by: Optional[str] = None
    sort_order: str = "asc"  # Default to ascending order, can be 'asc' or 'desc'
    db: Optional[str] = None  # Optional database name for filtering


class GetDataResponse(BaseModel):
    query_id: UUID
    limit: int
    offset: int
    rows: list[
        dict[str, Any]
    ]  # List of dictionaries representing the rows returned by the query
    total_rows: int  # Total number of rows available for the query (for pagination)


### Worker Request Models


class WorkerRequest(BaseModel):
    version: Version = Version.static
    session_id: UUID
    request_id: UUID
    refs: Optional[Refs]
    user: str
    request: str
    request_type: InteractiveRequestType = InteractiveRequestType.interactive_query
    response: Optional[str] = None
    status: RequestStatus
    parent_session_id: Optional[UUID] = None
    flow: Optional[FlowType] = FlowType.openai_multisteps
    model: Optional[ModelType] = ModelType.openai_default
    db: Optional[DBType] = DBType.legacy
    err: Optional[str] = None
    structured_response: Optional[StructuredResponse] = None
    query: Optional[GetQueryModel] = None


class McpServerRequest(BaseModel):
    model_config = ConfigDict(frozen=True)  # makes it hashable
    session_id: UUID
    request_id: UUID
    request: str
    flow: FlowType = FlowType.mcp
    model: ModelType = ModelType.openai_default
    db: DBType = DBType.legacy
