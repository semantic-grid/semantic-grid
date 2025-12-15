"""
Enhanced QueryPlan models with semantic concepts from MetricFlow.

This is a proposal/reference implementation - not yet integrated into the codebase.
See QUERY_PLAN_SEMANTIC_PROPOSAL.md for full design documentation.
"""

from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator

# =============================================================================
# 1. ENTITY TYPES FOR JOINS (Join Safety)
# =============================================================================


class EntityType(str, Enum):
    """
    Entity relationship types for join safety validation.
    Borrowed from MetricFlow's entity type system.
    """

    PRIMARY = "primary"  # Unique key, one row per entity (e.g., user_id in users)
    FOREIGN = "foreign"  # References another entity, may have nulls/duplicates
    UNIQUE = "unique"  # Unique but potentially incomplete (e.g., optional profile)
    NATURAL = "natural"  # Real-world identifier (e.g., email, phone, wallet)


class QueryPlanEntity(BaseModel):
    """Describes a join key/entity in a table."""

    name: str  # Entity name, e.g., "user", "transaction", "wallet"
    column: str  # Actual column name, e.g., "user_id", "wallet_address"
    entity_type: EntityType = EntityType.FOREIGN
    table: Optional[str] = None  # Which table this entity belongs to

    model_config = {"extra": "allow"}


class JoinCardinality(str, Enum):
    """Cardinality of join relationships."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class QueryPlanJoinV2(BaseModel):
    """
    Enhanced join description with entity metadata for safety validation.
    """

    # Basic join info (backwards compatible)
    left_table: Optional[str] = None
    right_table: Optional[str] = None
    join_type: Optional[str] = Field(default="left", alias="type")
    join_condition: Optional[str] = Field(default=None, alias="condition")

    # NEW: Entity-based join information
    left_entity: Optional[QueryPlanEntity] = None
    right_entity: Optional[QueryPlanEntity] = None

    # NEW: Join safety metadata
    cardinality: Optional[JoinCardinality] = None
    fan_out_risk: bool = False  # True if join may cause row multiplication

    model_config = {"populate_by_name": True, "extra": "allow"}

    def validate_safety(self) -> list[str]:
        """Return warnings for potentially unsafe joins."""
        warnings = []

        if self.left_entity and self.right_entity:
            left_type = self.left_entity.entity_type
            right_type = self.right_entity.entity_type

            # Foreign-to-foreign is dangerous (fan-out)
            if left_type == EntityType.FOREIGN and right_type == EntityType.FOREIGN:
                warnings.append(
                    f"Fan-out risk: joining {self.left_table} to {self.right_table} "
                    f"on foreign keys may multiply rows"
                )

        # Many-to-many explicit warning
        if self.cardinality == JoinCardinality.MANY_TO_MANY:
            warnings.append(
                f"Many-to-many join between {self.left_table} and {self.right_table} "
                f"- consider aggregating before joining"
            )

        if self.fan_out_risk:
            warnings.append(
                f"LLM flagged fan-out risk for join: {self.left_table} -> "
                f"{self.right_table}"
            )

        return warnings


# =============================================================================
# 2. DIMENSION TYPES (Time vs Categorical)
# =============================================================================


class DimensionType(str, Enum):
    """Dimension types for grouping/filtering."""

    CATEGORICAL = "categorical"  # Non-numeric attributes (location, status, name)
    TIME = "time"  # Date/timestamp values
    NUMERIC = "numeric"  # Numeric dimensions (e.g., age buckets, price ranges)


class TimeGranularity(str, Enum):
    """Time granularity options for date_trunc operations."""

    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class QueryPlanDimension(BaseModel):
    """
    Describes a dimension (grouping column) in the query plan.
    Aligned with MetricFlow's dimension concept.
    """

    name: str  # Column name or alias in output
    source_column: Optional[str] = None  # Original column if transformed
    table: Optional[str] = None  # Source table (for joins)
    dimension_type: DimensionType = DimensionType.CATEGORICAL

    # Time-specific fields
    time_granularity: Optional[TimeGranularity] = None  # For time dimensions
    time_zone: Optional[str] = None  # e.g., "UTC", "America/New_York"

    # Display metadata
    label: Optional[str] = None  # Human-readable label for UI
    description: Optional[str] = None

    model_config = {"extra": "allow"}

    def to_sql_expression(self, dialect: str = "trino") -> str:
        """Generate SQL expression for this dimension."""
        col = self.source_column or self.name

        if self.dimension_type == DimensionType.TIME and self.time_granularity:
            if dialect == "trino":
                return f"date_trunc('{self.time_granularity.value}', {col})"
            elif dialect == "clickhouse":
                granularity_map = {
                    "second": "toStartOfSecond",
                    "minute": "toStartOfMinute",
                    "hour": "toStartOfHour",
                    "day": "toDate",
                    "week": "toStartOfWeek",
                    "month": "toStartOfMonth",
                    "quarter": "toStartOfQuarter",
                    "year": "toStartOfYear",
                }
                func = granularity_map.get(self.time_granularity.value, "toDate")
                return f"{func}({col})"

        return col


# =============================================================================
# 3. MEASURE DEFINITIONS (Structured Aggregations)
# =============================================================================


class AggregationType(str, Enum):
    """
    Supported aggregation functions.
    Aligned with MetricFlow's aggregation types.
    """

    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    PERCENTILE = "percentile"
    SUM_BOOLEAN = "sum_boolean"  # Count of true values


class QueryPlanMeasure(BaseModel):
    """
    Describes a measure (aggregation) in the query plan.
    Aligned with MetricFlow's measure concept.
    """

    name: str  # Measure name/alias
    column: Optional[str] = None  # Column being aggregated ("*" for count)
    table: Optional[str] = None  # Source table
    aggregation: AggregationType = AggregationType.SUM

    # For percentile aggregations
    percentile_value: Optional[float] = None  # e.g., 0.5 for median, 0.95 for p95

    # Filters specific to this measure (conditional aggregation)
    measure_filter: Optional[str] = None  # e.g., "status = 'completed'"

    # Metadata
    label: Optional[str] = None  # Display label
    description: Optional[str] = None
    unit: Optional[str] = None  # e.g., "USD", "count", "percentage"

    # Lineage
    source: str = "inferred"  # "user_specified", "default", "inferred"

    model_config = {"extra": "allow"}

    def to_sql_expression(self, dialect: str = "trino") -> str:
        """Generate SQL aggregation expression."""
        col = self.column or "*"

        # Handle conditional aggregation
        if self.measure_filter:
            if dialect == "trino":
                col = f"CASE WHEN {self.measure_filter} THEN {col} END"
            elif dialect == "clickhouse":
                col = f"{col}If({self.measure_filter})"

        agg_map = {
            AggregationType.SUM: f"SUM({col})",
            AggregationType.COUNT: f"COUNT({col})",
            AggregationType.COUNT_DISTINCT: f"COUNT(DISTINCT {col})",
            AggregationType.AVERAGE: f"AVG({col})",
            AggregationType.MIN: f"MIN({col})",
            AggregationType.MAX: f"MAX({col})",
            AggregationType.MEDIAN: f"approx_percentile({col}, 0.5)"
            if dialect == "trino"
            else f"median({col})",
            AggregationType.PERCENTILE: f"approx_percentile({col}, {self.percentile_value or 0.5})"
            if dialect == "trino"
            else f"quantile({self.percentile_value or 0.5})({col})",
            AggregationType.SUM_BOOLEAN: f"SUM(CASE WHEN {col} THEN 1 ELSE 0 END)"
            if dialect == "trino"
            else f"countIf({col})",
        }

        return agg_map.get(self.aggregation, f"SUM({col})")


# =============================================================================
# 4. METRIC TYPES (Simple, Ratio, Cumulative, Derived)
# =============================================================================


class MetricType(str, Enum):
    """
    Metric calculation types.
    Describes how the final metric is computed from measures.
    """

    SIMPLE = "simple"  # Direct measure reference
    DERIVED = "derived"  # Expression combining other metrics
    RATIO = "ratio"  # One metric divided by another
    CUMULATIVE = "cumulative"  # Running total over time window
    CONVERSION = "conversion"  # Event conversion within time window


class QueryPlanMetric(BaseModel):
    """
    Describes the overall metric being computed.
    This is the "what" of the query at the highest level.
    """

    name: str  # Metric name
    metric_type: MetricType = MetricType.SIMPLE

    # For SIMPLE metrics
    measure: Optional[str] = None  # Reference to a measure name

    # For RATIO metrics
    numerator: Optional[str] = None  # Measure or metric for numerator
    denominator: Optional[str] = None  # Measure or metric for denominator

    # For DERIVED metrics
    expression: Optional[str] = None  # e.g., "revenue - cost"
    component_metrics: list[str] = []  # Metrics used in expression

    # For CUMULATIVE metrics
    cumulative_window: Optional[str] = None  # e.g., "7 days", "1 month", "all time"
    cumulative_type: str = "window"  # "window" (rolling) or "running" (all time)

    # For CONVERSION metrics
    base_event: Optional[str] = None  # e.g., "page_view"
    conversion_event: Optional[str] = None  # e.g., "purchase"
    conversion_window: Optional[str] = None  # e.g., "7 days"

    # Metadata
    label: Optional[str] = None
    description: Optional[str] = None

    model_config = {"extra": "allow"}

    def validate(self) -> list[str]:
        """Validate metric configuration."""
        errors = []

        if self.metric_type == MetricType.SIMPLE:
            if not self.measure:
                errors.append("Simple metric requires a measure reference")

        elif self.metric_type == MetricType.RATIO:
            if not self.numerator:
                errors.append("Ratio metric requires numerator")
            if not self.denominator:
                errors.append("Ratio metric requires denominator")

        elif self.metric_type == MetricType.DERIVED:
            if not self.expression:
                errors.append("Derived metric requires an expression")

        elif self.metric_type == MetricType.CUMULATIVE:
            if not self.measure:
                errors.append("Cumulative metric requires a measure reference")

        elif self.metric_type == MetricType.CONVERSION:
            if not self.base_event:
                errors.append("Conversion metric requires base_event")
            if not self.conversion_event:
                errors.append("Conversion metric requires conversion_event")

        return errors


# =============================================================================
# COMPLETE ENHANCED QUERY PLAN
# =============================================================================


class QueryPlanV2(BaseModel):
    """
    Enhanced query plan with semantic metadata.
    Combines our dynamic LLM approach with MetricFlow concepts.
    """

    model_config = {"extra": "allow"}

    # === Core Identity ===
    plan_summary: str = ""
    estimated_complexity: str = "moderate"  # "simple", "moderate", "complex"
    reason_for_approval: Optional[str] = None

    # === Tables (Semantic Models) ===
    tables: list[str] = []
    primary_table: str = ""

    # === Joins with Entity Types ===
    joins: list[Union[QueryPlanJoinV2, str]] = []

    # === Dimensions (Grouping) - NEW ===
    dimensions: list[Union[QueryPlanDimension, str]] = []
    primary_time_dimension: Optional[str] = None
    default_time_granularity: TimeGranularity = TimeGranularity.DAY

    # === Measures (Aggregations) - NEW ===
    measures: list[Union[QueryPlanMeasure, str]] = []

    # === Metric (Top-Level Calculation) - NEW ===
    metric: Optional[QueryPlanMetric] = None

    # === Filters ===
    filters: list[str] = []  # Keep simple for now

    # === Ordering & Limits ===
    order_by: list[str] = []
    limit: Optional[Union[int, str]] = None
    group_by: list[str] = []

    # === Assumptions & Defaults ===
    assumptions: list[str] = []
    default_params: list[str] = []

    # === Schema Context ===
    relevant_schema: Optional[str] = None

    # === Backwards Compatibility (Deprecated) ===
    columns_selected: list[str] = []  # Use dimensions instead
    aggregations: list[str] = []  # Use measures instead

    # --- Validators (same coercion logic as current QueryPlan) ---

    @field_validator(
        "tables",
        "columns_selected",
        "group_by",
        "order_by",
        "assumptions",
        "default_params",
        "filters",
        "aggregations",
        mode="before",
    )
    @classmethod
    def coerce_string_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(item) for item in v if item is not None]
        return []

    @field_validator("joins", "dimensions", "measures", mode="before")
    @classmethod
    def coerce_complex_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, dict):
            return [v]
        if isinstance(v, list):
            return v
        return []

    def validate_plan(self) -> tuple[list[str], list[str]]:
        """
        Validate the query plan for safety and consistency.
        Returns (errors, warnings).
        """
        errors = []
        warnings = []

        # 1. Join Safety
        for join in self.joins:
            if isinstance(join, QueryPlanJoinV2):
                warnings.extend(join.validate_safety())

        # 2. Time Dimension Consistency
        if self.primary_time_dimension:
            time_dims = [
                d
                for d in self.dimensions
                if isinstance(d, QueryPlanDimension)
                and d.dimension_type == DimensionType.TIME
            ]
            if not any(d.name == self.primary_time_dimension for d in time_dims):
                warnings.append(
                    f"Primary time dimension '{self.primary_time_dimension}' "
                    f"not found in dimensions list"
                )

        # 3. Metric Validation
        if self.metric:
            errors.extend(self.metric.validate())

            if self.metric.metric_type == MetricType.CUMULATIVE:
                if not self.primary_time_dimension:
                    warnings.append(
                        "Cumulative metric without time dimension may produce "
                        "unexpected results"
                    )

        # 4. Measure References
        measure_names = {
            m.name for m in self.measures if isinstance(m, QueryPlanMeasure)
        }
        if self.metric and self.metric.measure:
            if self.metric.measure not in measure_names:
                warnings.append(
                    f"Metric references measure '{self.metric.measure}' "
                    f"not defined in measures list"
                )

        return errors, warnings


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example: "Show me 7-day rolling average DAU by country"
    plan = QueryPlanV2(
        plan_summary="Calculate 7-day rolling average of daily active users by country",
        estimated_complexity="moderate",
        tables=["iceberg.analytics.user_activity", "iceberg.reference.countries"],
        primary_table="iceberg.analytics.user_activity",
        joins=[
            QueryPlanJoinV2(
                left_table="iceberg.analytics.user_activity",
                right_table="iceberg.reference.countries",
                join_type="left",
                join_condition="on country_code",
                left_entity=QueryPlanEntity(
                    name="country",
                    column="country_code",
                    entity_type=EntityType.FOREIGN,
                ),
                right_entity=QueryPlanEntity(
                    name="country", column="code", entity_type=EntityType.PRIMARY
                ),
                cardinality=JoinCardinality.MANY_TO_ONE,
            )
        ],
        dimensions=[
            QueryPlanDimension(
                name="activity_date",
                source_column="activity_timestamp",
                dimension_type=DimensionType.TIME,
                time_granularity=TimeGranularity.DAY,
                label="Date",
            ),
            QueryPlanDimension(
                name="country_name",
                source_column="name",
                table="countries",
                dimension_type=DimensionType.CATEGORICAL,
                label="Country",
            ),
        ],
        primary_time_dimension="activity_date",
        measures=[
            QueryPlanMeasure(
                name="daily_active_users",
                column="user_id",
                aggregation=AggregationType.COUNT_DISTINCT,
                label="DAU",
            )
        ],
        metric=QueryPlanMetric(
            name="rolling_7d_avg_dau",
            metric_type=MetricType.CUMULATIVE,
            measure="daily_active_users",
            cumulative_window="7 days",
            label="7-Day Rolling Avg DAU",
        ),
        assumptions=[
            "Using last 30 days of data for the rolling calculation",
            "DAU defined as distinct users with any activity",
        ],
    )

    # Validate
    errors, warnings = plan.validate_plan()
    print("Errors:", errors)
    print("Warnings:", warnings)

    # Generate dimension SQL
    for dim in plan.dimensions:
        if isinstance(dim, QueryPlanDimension):
            print(f"{dim.name}: {dim.to_sql_expression('trino')}")

    # Generate measure SQL
    for measure in plan.measures:
        if isinstance(measure, QueryPlanMeasure):
            print(f"{measure.name}: {measure.to_sql_expression('trino')}")
