from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

### General Models


class Refs(BaseModel):
    parent: Optional[UUID] = None
    steps: Optional[list[UUID]] = None
    cols: Optional[list[str]] = None
    rows: Optional[list[list[Union[str, int, float]]]] = None


class RequestStatus(str, Enum):
    new = "New"
    intent = "Intent"
    planning = "Planning"  # Transient: query plan is being generated
    feedback_requested = (
        "FeedbackRequested"  # Terminal: awaiting user approval/feedback
    )
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
    plan_approval = "plan_approval"  # User approving a query plan
    plan_amendment = "plan_amendment"  # User requesting changes to a query plan
    clarification = "clarification"  # Agent asking a clarifying question
    clarification_response = (
        "clarification_response"  # User responding to clarification
    )
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


class PlanningMode(str, Enum):
    """Controls when the planner step is used in interactive flow.

    - never: Skip planning, go directly to SQL generation (original behavior)
    - intent_based: LLM decides based on query complexity (default)
    - always: Always run planning step before SQL generation
    """

    never = "never"
    intent_based = "intent_based"
    always = "always"


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


class ChartMetadata(BaseModel):
    """
    Chart visualization metadata for query results.

    - suggested_chart: LLM's suggested chart type based on query intent
    - available_charts: Empirically validated chart types based on result structure
    - chart_config: Optional hints for chart rendering (axis labels, title, etc.)
    """

    suggested_chart: Optional[str] = None  # "bar", "line", "pie", "table", "none"
    available_charts: Optional[list[str]] = None  # Validated options
    chart_config: Optional[dict[str, Any]] = None  # Rendering hints


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
    chart: Optional[ChartMetadata] = None
    refs: Optional[Refs] = None
    view: Optional[View] = None
    description: Optional[str] = None
    # Performance metrics for query execution estimation
    performance_warning: Optional[bool] = None
    estimated_rows: Optional[int] = None
    estimated_size_gb: Optional[float] = None


class ClarificationData(BaseModel):
    """Structured clarification question for frontend display."""

    question: str  # The clarifying question to ask the user
    options: Optional[list[str]] = None  # Multiple choice options (if applicable)
    context: Optional[str] = None  # Why we're asking (helps user understand)
    allow_freeform: bool = True  # Allow typed response vs only predefined options


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
    # Query plan for multistep flow (populated when status=Planning)
    query_plan: Optional["QueryPlan"] = None
    # Reason for re-planning (when query generation failed and new plan is presented)
    replan_reason: Optional[str] = None
    # Response type discriminator for "ask user" patterns
    # Values: None/"query" (default), "plan_approval", "clarification", etc.
    response_type: Optional[str] = None
    # Clarification data (populated when response_type="clarification")
    clarification: Optional[ClarificationData] = None


class IntentAnalysis(BaseModel):
    request_type: InteractiveRequestType = InteractiveRequestType.interactive_query
    intent: Optional[str] = None
    summary: Optional[str] = None
    response: Optional[str] = None
    # If True, query planner step will generate a plan for user approval
    requires_plan_approval: bool = False
    # Clarification support - when LLM needs more info before proceeding
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    clarification_options: Optional[list[str]] = None  # Multiple choice options
    clarification_context: Optional[str] = None  # Why we're asking


### Query Plan Models (for multistep flow)


class QueryPlanJoin(BaseModel):
    """Describes a join between two tables in the query plan."""

    left_table: Optional[str] = None
    right_table: Optional[str] = None
    join_type: Optional[str] = Field(
        default=None, alias="type"
    )  # "inner", "left", "right", "full", "cross"
    join_condition: Optional[str] = Field(
        default=None, alias="condition"
    )  # human-readable, e.g., "on user_id"

    model_config = {"populate_by_name": True, "extra": "allow"}


class QueryPlanFilter(BaseModel):
    """Describes a filter/WHERE condition in the query plan."""

    column: Optional[str] = None
    operator: Optional[str] = (
        None  # "=", ">", "<", ">=", "<=", "!=", "like", "in", "between"
    )
    value: Optional[str] = None  # human-readable value representation
    source: str = "inferred"  # "user_specified", "default", "inferred"

    model_config = {"extra": "allow"}


class QueryPlanAggregation(BaseModel):
    """Describes an aggregation in the query plan."""

    function: Optional[str] = (
        None  # "count", "sum", "avg", "min", "max", "count_distinct"
    )
    column: Optional[str] = None  # column being aggregated, or "*" for count(*)
    alias: Optional[str] = None  # result column name
    description: Optional[str] = None  # human-readable description as fallback

    model_config = {"extra": "allow"}


class QueryPlan(BaseModel):
    """
    Human-readable query plan for user approval before SQL generation.

    This captures the LLM's understanding of what the query will do,
    allowing users to verify intent before SQL is generated.
    """

    # Allow both lowercase (code) and PascalCase (LLM output) field names
    model_config = {"extra": "allow", "populate_by_name": True}

    # Tables involved
    tables: list[str] = Field(default=[], alias="Tables")
    primary_table: str = Field(default="", alias="PrimaryTable")

    # Relationships
    # Accept either structured objects or simple strings for flexibility
    joins: list[Union[QueryPlanJoin, str]] = Field(default=[], alias="Joins")

    # Data selection
    columns_selected: list[str] = Field(
        default=[], alias="ColumnsSelected"
    )  # columns to return (human-readable)
    # Accept either structured objects or simple strings for flexibility
    filters: list[Union[QueryPlanFilter, str]] = Field(default=[], alias="Filters")

    # Aggregations and grouping
    # Accept either structured objects or simple strings for flexibility
    aggregations: list[Union[QueryPlanAggregation, str]] = Field(
        default=[], alias="Aggregations"
    )
    group_by: list[str] = Field(default=[], alias="Grouping")

    # Ordering and limits
    order_by: list[str] = Field(
        default=[], alias="Ordering"
    )  # e.g., ["volume descending", "date ascending"]
    limit: Optional[Union[int, str]] = Field(
        default=None, alias="Limit"
    )  # Accept string explanations from LLM

    # Assumptions and defaults applied
    assumptions: list[str] = Field(
        default=[], alias="Assumptions"
    )  # e.g., "Assuming 'recent' means last 7 days"
    default_params: list[str] = Field(
        default=[], alias="DefaultParameters"
    )  # e.g., "Using default limit of 1000 rows"

    # Human-readable summary
    plan_summary: str = Field(
        default="", alias="PlanSummary"
    )  # 2-3 sentence explanation of what the query will do

    # Complexity indicators (for transparency)
    estimated_complexity: str = "moderate"  # "simple", "moderate", "complex"
    reason_for_approval: Optional[str] = None  # why this query needs approval

    # Schema context for SQL generation (extracted during planning)
    relevant_schema: Optional[str] = None  # Schema subset for tables in this plan

    # Columns actually referenced (for validation against schema)
    # LLM must list actual column names from schema, not user's conceptual names
    columns_referenced: list[str] = []  # e.g., ["event_timestamp", "nas_identifier"]

    @field_validator(
        "tables",
        "columns_selected",
        "columns_referenced",
        "group_by",
        "order_by",
        "assumptions",
        "default_params",
        mode="before",
    )
    @classmethod
    def coerce_string_to_list(cls, v):
        """Handle LLM returning a string instead of a list."""
        if v is None:
            return []
        if isinstance(v, str):
            # If it's a non-empty string, wrap it in a list
            return [v] if v.strip() else []
        if isinstance(v, list):
            # Filter out any non-string items and convert to strings
            return [str(item) for item in v if item is not None]
        return []

    @field_validator("joins", "filters", "aggregations", mode="before")
    @classmethod
    def coerce_complex_to_list(cls, v):
        """Handle LLM returning a string instead of a list for complex fields."""
        if v is None:
            return []
        if isinstance(v, str):
            # If it's a non-empty string, wrap it in a list
            return [v] if v.strip() else []
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            # Single object, wrap in list
            return [v]
        return []

    @field_validator("primary_table", "plan_summary", mode="before")
    @classmethod
    def coerce_to_string(cls, v):
        """Handle LLM returning non-string values for string fields."""
        if v is None:
            return ""
        if isinstance(v, list):
            # If list, join elements or return empty
            return ", ".join(str(item) for item in v) if v else ""
        return str(v)

    @field_validator("relevant_schema", mode="before")
    @classmethod
    def coerce_relevant_schema_to_string(cls, v):
        """Handle LLM returning a list instead of a string for relevant_schema."""
        if v is None:
            return None
        if isinstance(v, list):
            # Join list items with double newline separator to preserve structure
            return "\n\n".join(str(item) for item in v if item is not None)
        if isinstance(v, str):
            return v if v.strip() else None
        return str(v) if v else None

    @field_validator("limit", mode="before")
    @classmethod
    def coerce_limit(cls, v):
        """Handle LLM returning empty list or other unexpected values for limit."""
        if v is None:
            return None
        if isinstance(v, list):
            return None if len(v) == 0 else str(v)
        if isinstance(v, (int, str)):
            return v
        return str(v)

    @field_validator("estimated_complexity", mode="before")
    @classmethod
    def coerce_complexity(cls, v):
        """Ensure complexity is a valid string, default to 'moderate'."""
        if v is None or (isinstance(v, list) and len(v) == 0):
            return "moderate"
        if isinstance(v, list):
            return str(v[0]) if v else "moderate"
        valid_values = {"simple", "moderate", "complex"}
        str_v = str(v).lower()
        return str_v if str_v in valid_values else "moderate"


### Query Plan DB Models (for first-class query plan storage)


class CreateQueryPlanModel(BaseModel):
    """Model for creating a new query plan record in the database."""

    session_id: UUID
    request_id: UUID
    parent_id: Optional[UUID] = None  # Previous plan iteration
    original_intent: str
    amendment_feedback: Optional[str] = None  # User feedback that triggered this plan

    # Plan content (from QueryPlan)
    tables: list[str] = []
    primary_table: str = ""
    joins: list[Any] = []
    columns_selected: list[str] = []
    columns_referenced: list[str] = []  # Actual column names for validation
    filters: list[Any] = []
    aggregations: list[Any] = []
    group_by: list[str] = []
    order_by: list[str] = []
    plan_limit: Optional[str] = None
    assumptions: list[str] = []
    default_params: list[str] = []
    plan_summary: str
    estimated_complexity: str = "moderate"
    reason_for_approval: Optional[str] = None
    relevant_schema: Optional[str] = None

    @classmethod
    def from_query_plan(
        cls,
        plan: "QueryPlan",
        session_id: UUID,
        request_id: UUID,
        original_intent: str,
        parent_id: Optional[UUID] = None,
        amendment_feedback: Optional[str] = None,
    ) -> "CreateQueryPlanModel":
        """Create a DB model from a QueryPlan."""
        return cls(
            session_id=session_id,
            request_id=request_id,
            parent_id=parent_id,
            original_intent=original_intent,
            amendment_feedback=amendment_feedback,
            tables=plan.tables,
            primary_table=plan.primary_table,
            joins=plan.joins,
            columns_selected=plan.columns_selected,
            columns_referenced=plan.columns_referenced,
            filters=plan.filters,
            aggregations=plan.aggregations,
            group_by=plan.group_by,
            order_by=plan.order_by,
            plan_limit=str(plan.limit) if plan.limit else None,
            assumptions=plan.assumptions,
            default_params=plan.default_params,
            plan_summary=plan.plan_summary,
            estimated_complexity=plan.estimated_complexity,
            reason_for_approval=plan.reason_for_approval,
            relevant_schema=plan.relevant_schema,
        )


class GetQueryPlanModel(BaseModel):
    """Model for reading a query plan record from the database."""

    plan_id: UUID
    session_id: UUID
    request_id: UUID
    parent_id: Optional[UUID] = None
    original_intent: str
    amendment_feedback: Optional[str] = None

    # Plan content
    tables: list[str] = []
    primary_table: str = ""
    joins: list[Any] = []
    columns_selected: list[str] = []
    columns_referenced: list[str] = []
    filters: list[Any] = []
    aggregations: list[Any] = []
    group_by: list[str] = []
    order_by: list[str] = []
    plan_limit: Optional[str] = None
    assumptions: list[str] = []
    default_params: list[str] = []
    plan_summary: str
    estimated_complexity: str = "moderate"
    reason_for_approval: Optional[str] = None
    relevant_schema: Optional[str] = None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    def to_query_plan(self) -> "QueryPlan":
        """Convert DB model back to QueryPlan for API responses."""
        return QueryPlan(
            tables=self.tables,
            primary_table=self.primary_table,
            joins=self.joins,
            columns_selected=self.columns_selected,
            columns_referenced=self.columns_referenced,
            filters=self.filters,
            aggregations=self.aggregations,
            group_by=self.group_by,
            order_by=self.order_by,
            limit=self.plan_limit,
            assumptions=self.assumptions,
            default_params=self.default_params,
            plan_summary=self.plan_summary,
            estimated_complexity=self.estimated_complexity,
            reason_for_approval=self.reason_for_approval,
            relevant_schema=self.relevant_schema,
        )


class QueryPlanChainModel(BaseModel):
    """Model for returning a chain of query plans (amendment history)."""

    plans: list[GetQueryPlanModel]
    total_iterations: int


class PromptItemType(str, Enum):
    db_struct = "DBStruct"
    query_example = "QueryExample"
    data_description = "DataDescription"
    ref_sources = "RefSources"
    instruction = "Instruction"
    data_sample = "DataSample"
    slot_schema = "SlotSchema"
    sql_dialect = "SQLDialect"
    domain_model = "DomainModel"
    assembled_prompt = "AssembledPrompt"  # Full assembled prompt from slot


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
    chart: Optional[ChartMetadata] = None
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
    chart: Optional[ChartMetadata] = None
    err: Optional[str] = None


class GetQueryModel(CreateQueryModel):
    query_id: UUID
    request_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    # data fetches for this query (populated in admin endpoints)
    data_fetches: Optional[list["GetDataFetchModel"]] = None


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
    # data fetches for this request's query (populated in admin endpoints)
    data_fetches: Optional[list["GetDataFetchModel"]] = None
    # query plan for multi-step flow - LEGACY (populated when status=FeedbackRequested)
    # New code should use response_type + payload instead
    query_plan: Optional["QueryPlan"] = None
    # response type discriminator for unified response handling
    response_type: Optional[str] = (
        None  # "query", "plan_approval", "clarification", "chat", "error"
    )
    # type-specific payload (shape varies by response_type)
    payload: Optional[dict[str, Any]] = None
    # admin fields
    is_test: Optional[bool] = None
    is_fixed: Optional[bool] = None
    fixed_by: Optional[str] = None
    fixed_ts: Optional[datetime] = None
    fix_comment: Optional[str] = None


class UpdateRequestStatusModel(BaseModel):
    review: Optional[str] = None
    rating: Optional[int] = None
    status: Optional[RequestStatus] = None


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
    query_plan: Optional[dict[str, Any]] = None  # JSON serialized QueryPlan (legacy)
    # Response type discriminator for unified response handling
    response_type: Optional[str] = (
        None  # "query", "plan_approval", "clarification", "chat", "error"
    )
    # Type-specific payload (shape varies by response_type)
    payload: Optional[dict[str, Any]] = None


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


### Admin Models


class AdminRequestsResponse(BaseModel):
    """Paginated response for admin requests endpoint."""

    requests: list[GetRequestModel]
    total: int
    limit: int
    offset: int


class PatchAdminRequestModel(BaseModel):
    """Model for updating admin-specific fields on a request."""

    is_test: Optional[bool] = None
    is_fixed: Optional[bool] = None
    fix_comment: Optional[str] = None


class AdminQueriesResponse(BaseModel):
    """Paginated response for admin queries endpoint."""

    queries: list[GetQueryModel]
    total: int
    limit: int
    offset: int


### Query Explorer Models (for admin observability)


class QueryExplorerRequestSummary(BaseModel):
    """Summary of a request that contributed to a query."""

    request_id: UUID
    created_at: datetime
    request_type: Optional[str] = None  # initial, plan_approval, plan_amendment, replan
    request_text: str  # Original request text
    status: RequestStatus
    # Plan info (if this request generated a plan)
    has_plan: bool = False
    plan_summary: Optional[str] = None
    plan_tables: Optional[list[str]] = None
    # SQL attempts (if this request generated SQL)
    sql_attempts: int = 0
    sql_success: bool = False
    # Outcome description
    outcome: Optional[str] = None  # e.g., "Plan v1 generated", "SQL failed → replan"
    # Trace summary
    has_trace: bool = False
    trace_llm_calls: int = 0
    trace_repairs: int = 0
    trace_errors: int = 0
    trace_duration_ms: int = 0


class QueryExplorerItem(BaseModel):
    """A query with its full journey from intent to result."""

    # Query info
    query_id: UUID
    created_at: datetime
    summary: Optional[str] = None
    sql: Optional[str] = None
    row_count: Optional[int] = None
    rating: Optional[int] = None

    # Session/user info
    session_id: UUID
    user: Optional[str] = None

    # The original intent that started this query journey
    original_intent: Optional[str] = None

    # Aggregated metrics
    plan_iterations: int = 0  # How many plans were generated
    sql_attempts: int = 0  # Total SQL generation attempts across all requests
    total_duration_ms: int = 0  # From first request to query creation
    total_tokens_in: int = 0
    total_tokens_out: int = 0

    # Contributing requests (for expansion)
    requests: list[QueryExplorerRequestSummary] = []

    # Status flags
    had_replan: bool = False  # True if SQL generation failed and triggered replan
    had_amendments: bool = False  # True if user amended the plan

    # Data fetches for this query
    data_fetches: list["GetDataFetchModel"] = []


class QueryExplorerResponse(BaseModel):
    """Paginated response for query explorer endpoint."""

    queries: list[QueryExplorerItem]
    total: int
    limit: int
    offset: int


### Data Fetch Models


class DataFetchStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    cancelled = "cancelled"
    timed_out = "timed_out"


class DataFetchQueryParams(BaseModel):
    """Query parameters for a data fetch operation."""

    limit: int = 100
    offset: int = 0
    sort_by: Optional[str] = None
    sort_order: str = "asc"
    force: bool = False


class CreateDataFetchModel(BaseModel):
    """Model for creating a new data fetch record."""

    query_id: UUID
    request_id: Optional[UUID] = None
    task_id: Optional[str] = None
    requestor: str = "user"  # 'user' or 'system'
    query_params: Optional[DataFetchQueryParams] = None


class UpdateDataFetchModel(BaseModel):
    """Model for updating a data fetch record."""

    status: Optional[DataFetchStatus] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    row_count: Optional[int] = None
    error: Optional[str] = None
    cache_hit: Optional[bool] = None


class GetDataFetchModel(BaseModel):
    """Model for reading a data fetch record."""

    id: UUID
    query_id: UUID
    request_id: Optional[UUID] = None
    task_id: Optional[str] = None
    requestor: str
    status: DataFetchStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    query_params: Optional[dict[str, Any]] = None
    row_count: Optional[int] = None
    error: Optional[str] = None
    cache_hit: bool = False


class AdminDataFetchesResponse(BaseModel):
    """Paginated response for admin data fetches endpoint."""

    data_fetches: list[GetDataFetchModel]
    total: int
    limit: int
    offset: int


### Prompt Version Models (for LLM observability)


class TraceStepType(str, Enum):
    request_context = "request_context"
    prompt_assembly = "prompt_assembly"
    mcp_call = "mcp_call"
    llm_call = "llm_call"
    validation = "validation"
    repair = "repair"
    sql_execution = "sql_execution"
    error = "error"


class CreatePromptVersionModel(BaseModel):
    """Model for creating/registering a prompt version."""

    content_hash: str
    source: str = "db_meta"
    source_version: Optional[str] = None
    prompt_item_type: PromptItemType
    content: str
    metadata: Optional[dict[str, Any]] = None


class GetPromptVersionModel(BaseModel):
    """Model for reading a prompt version record."""

    id: UUID
    content_hash: str
    source: str
    source_version: Optional[str] = None
    prompt_item_type: PromptItemType
    content: str
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime


### Request Trace Models (for LLM observability)


class CreateTraceStepModel(BaseModel):
    """Model for creating a trace step record."""

    request_id: UUID
    step_number: int
    step_type: TraceStepType

    # For LLM calls
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    input_hash: Optional[str] = None
    output_raw: Optional[str] = None
    output_parsed: Optional[dict[str, Any]] = None

    # For MCP calls
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    prompt_version_ids: Optional[list[UUID]] = None

    # For validation
    validation_type: Optional[str] = None
    validation_success: Optional[bool] = None
    validation_errors: Optional[list[dict[str, Any]]] = None

    # Common fields
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class GetTraceStepModel(BaseModel):
    """Model for reading a trace step record."""

    id: UUID
    request_id: UUID
    step_number: int
    step_type: TraceStepType

    # For LLM calls
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    input_hash: Optional[str] = None
    output_raw: Optional[str] = None
    output_parsed: Optional[dict[str, Any]] = None

    # For MCP calls
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    prompt_version_ids: Optional[list[UUID]] = None

    # For validation
    validation_type: Optional[str] = None
    validation_success: Optional[bool] = None
    validation_errors: Optional[list[dict[str, Any]]] = None

    # Common fields
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime


class TraceSummary(BaseModel):
    """Summary of trace execution for quick stats on request table."""

    total_steps: int
    llm_calls: int
    mcp_calls: int
    validations: int
    repairs: int
    total_tokens_in: int
    total_tokens_out: int
    total_duration_ms: int
    has_errors: bool


class GetRequestTraceModel(BaseModel):
    """Full trace for a request including all steps."""

    request_id: UUID
    steps: list[GetTraceStepModel]
    summary: TraceSummary


class AdminTracesResponse(BaseModel):
    """Paginated response for admin traces endpoint."""

    traces: list[GetRequestTraceModel]
    total: int
    limit: int
    offset: int


class AdminPromptVersionsResponse(BaseModel):
    """Paginated response for admin prompt versions endpoint."""

    prompt_versions: list[GetPromptVersionModel]
    total: int
    limit: int
    offset: int
