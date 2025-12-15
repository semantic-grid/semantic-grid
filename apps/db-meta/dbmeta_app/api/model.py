from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class PromptItemType(str, Enum):
    db_struct = "DBStruct"
    data_sample = "DataSample"
    query_example = "QueryExample"
    instruction = "Instruction"
    data_description = "DataDescription"
    sql_dialect = "SQLDialect"


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
