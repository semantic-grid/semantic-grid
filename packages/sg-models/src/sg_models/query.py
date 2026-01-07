"""Query result models."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class QueryMetadata(BaseModel):
    """Metadata about a query execution."""

    query_id: str = Field(..., description="Unique query identifier")
    sql: str = Field(..., description="The SQL that was executed")
    intent: str | None = Field(default=None, description="Original natural language intent")

    # Execution info
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = Field(default=0, description="Query execution time in milliseconds")
    rows_returned: int = Field(default=0, description="Number of rows returned")
    rows_scanned: int | None = Field(default=None, description="Number of rows scanned (if known)")

    # Cost info
    estimated_cost: float | None = Field(default=None, description="Estimated query cost")
    cost_tier: str = Field(default="auto", description="Cost tier: auto, confirm, or reject")

    # Caching
    cache_hit: bool = Field(default=False, description="Whether result was from cache")
    cache_key: str | None = Field(default=None, description="Cache key if applicable")

    # Lineage
    provider_id: str | None = Field(default=None, description="Database provider ID")
    plan_id: str | None = Field(default=None, description="Query plan ID if planned")


class QueryResult(BaseModel):
    """Result of a query execution."""

    data: list[dict[str, Any]] = Field(default_factory=list, description="Query result rows")
    columns: list[str] = Field(default_factory=list, description="Column names in order")
    column_types: dict[str, str] = Field(
        default_factory=dict, description="Column name to SQL type mapping"
    )
    metadata: QueryMetadata = Field(..., description="Query execution metadata")

    # Pagination
    total_rows: int | None = Field(
        default=None, description="Total rows available (if known, for pagination)"
    )
    offset: int = Field(default=0, description="Offset for pagination")
    limit: int | None = Field(default=None, description="Limit applied")
    has_more: bool = Field(default=False, description="Whether more rows are available")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump()
