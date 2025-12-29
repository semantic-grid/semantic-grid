from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class PromptItemType(str, Enum):
    db_struct = "DBStruct"
    db_table_list = (
        "DBTableList"  # Lightweight: table names + descriptions only (no columns)
    )
    data_sample = "DataSample"
    query_example = "QueryExample"
    instruction = "Instruction"
    data_description = "DataDescription"
    sql_dialect = "SQLDialect"
    domain_model = "DomainModel"


class GetPromptModel(BaseModel):
    user_request: str
    db: str | None = None


class GetPromptItemsRequestV2(BaseModel):
    """Request model for prompt_items_v2 with parameterized item selection."""

    user_request: Optional[str] = None
    db: Optional[str] = None
    items: list[PromptItemType] = [
        PromptItemType.db_struct,
        PromptItemType.query_example,
        PromptItemType.instruction,
        PromptItemType.sql_dialect,
    ]
    schema_top_k: int = 10
    examples_top_k: int = 5


class TestSqlModel(BaseModel):
    sql: str
    db: str | None = None


class GetSchemaModel(BaseModel):
    db: str | None = None


class PromptItem(BaseModel):
    text: str
    prompt_item_type: PromptItemType
    score: int
    # Lineage tracking fields (optional for backward compatibility)
    content_hash: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class PromptsSetModel(BaseModel):
    prompt_items: list[PromptItem]
    source: str
    version: Optional[str] = None


class ValidatePlanRequest(BaseModel):
    """Request model for validating query plan tables and columns."""

    tables: list[str]
    columns_referenced: list[str]
    db: Optional[str] = None


class ValidationError(BaseModel):
    """Single validation error."""

    error_type: str  # "missing_table" or "missing_column"
    name: str  # The table or column name that's missing
    suggestion: Optional[str] = None  # Suggested alternative if found


class ValidatePlanResult(BaseModel):
    """Result of plan validation."""

    valid: bool
    errors: list[ValidationError] = []
    available_tables: Optional[list[str]] = None  # Only included if there are errors


# --------------------------------------------------------------------------
# Models for get_table_details MCP tool (granular schema exploration)
# --------------------------------------------------------------------------


class TableDetailsInclude(str, Enum):
    """Options for what to include in table details response."""

    relationships = "relationships"  # PK-FK constraints
    cardinality = "cardinality"  # Distinct value counts
    low_cardinality_values = "low_cardinality_values"  # Actual values for low-card cols
    ranges = "ranges"  # Min/max for numeric/date columns
    indexes = "indexes"  # Index information


class GetTableDetailsRequest(BaseModel):
    """Request model for get_table_details MCP tool."""

    db: Optional[str] = None  # "wh", "wh_new", "wh_v2"
    tables: list[str]  # Fully qualified table names
    include: list[TableDetailsInclude] = [
        TableDetailsInclude.relationships,
        TableDetailsInclude.cardinality,
        TableDetailsInclude.ranges,
    ]
    cardinality_threshold: int = (
        100  # Max distinct values to consider "low cardinality"
    )
    sample_size: int = 10000  # Rows to sample for stats


class ForeignKeyInfo(BaseModel):
    """Foreign key relationship information."""

    columns: list[str]  # Source columns
    referred_table: str  # Target table
    referred_columns: list[str]  # Target columns
    constraint_name: Optional[str] = None


class ColumnDetails(BaseModel):
    """Detailed column information including statistics."""

    name: str
    type: str
    nullable: bool
    description: Optional[str] = None
    example: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    # Statistics (populated based on 'include' options)
    distinct_count: Optional[int] = None  # Approximate cardinality
    is_low_cardinality: Optional[bool] = None  # distinct_count < threshold
    distinct_values: Optional[list[str]] = None  # If low cardinality
    min_value: Optional[str] = None  # For numeric/date columns
    max_value: Optional[str] = None  # For numeric/date columns


class IndexInfo(BaseModel):
    """Index information for a table."""

    name: str
    columns: list[str]
    is_unique: bool = False
    is_primary: bool = False


class TableDetails(BaseModel):
    """Detailed metadata for a single table."""

    table_name: str
    description: Optional[str] = None
    row_count_estimate: Optional[int] = None
    primary_key: Optional[list[str]] = None
    foreign_keys: list[ForeignKeyInfo] = []
    indexes: list[IndexInfo] = []
    columns: list[ColumnDetails] = []


class GetTableDetailsResponse(BaseModel):
    """Response model for get_table_details MCP tool."""

    tables: list[TableDetails]
    content_hash: str
    metadata: dict[str, Any] = {}
