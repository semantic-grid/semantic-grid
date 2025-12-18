# Enhanced QueryPlan with Semantic Concepts

This document proposes enhancements to our QueryPlan model, borrowing concepts from dbt's MetricFlow while maintaining our dynamic LLM-driven approach.

## Design Principles

1. **Backwards Compatible**: New fields are optional; existing plans continue to work
2. **LLM-Friendly**: Structures are simple enough for LLMs to generate reliably
3. **Validation-Ready**: Entity types enable join safety checks
4. **Human-Readable**: Everything remains understandable to end users

---

## 1. Entity Types for Joins (Join Safety)

### Current
```python
class QueryPlanJoin(BaseModel):
    left_table: Optional[str] = None
    right_table: Optional[str] = None
    join_type: Optional[str] = None  # "inner", "left", etc.
    join_condition: Optional[str] = None  # "on user_id"
```

### Enhanced
```python
class EntityType(str, Enum):
    """Entity relationship types (from MetricFlow)."""
    PRIMARY = "primary"    # Unique key, one row per entity (e.g., user_id in users table)
    FOREIGN = "foreign"    # References another entity, may have nulls/duplicates
    UNIQUE = "unique"      # Unique but potentially incomplete (e.g., optional profile)
    NATURAL = "natural"    # Real-world identifier (e.g., email, phone)


class QueryPlanEntity(BaseModel):
    """Describes a join key/entity in a table."""
    name: str                           # Entity name, e.g., "user", "transaction"
    column: str                         # Actual column name, e.g., "user_id"
    entity_type: EntityType = EntityType.FOREIGN
    table: Optional[str] = None         # Which table this entity belongs to


class QueryPlanJoin(BaseModel):
    """Describes a join between two tables with entity metadata."""
    
    left_table: Optional[str] = None
    right_table: Optional[str] = None
    join_type: Optional[str] = Field(default=None, alias="type")
    join_condition: Optional[str] = Field(default=None, alias="condition")
    
    # NEW: Entity-based join information
    left_entity: Optional[QueryPlanEntity] = None   # Entity on left side
    right_entity: Optional[QueryPlanEntity] = None  # Entity on right side
    
    # NEW: Join safety metadata
    cardinality: Optional[str] = None  # "one_to_one", "one_to_many", "many_to_many"
    fan_out_risk: bool = False         # True if join may cause row multiplication
```

### Join Safety Validation Rules

Based on MetricFlow's entity type matrix:

| Left Entity | Right Entity | Allowed? | Risk |
|-------------|--------------|----------|------|
| PRIMARY | PRIMARY | Yes | None |
| PRIMARY | UNIQUE | Yes | None |
| PRIMARY | FOREIGN | Yes (left join) | Possible nulls |
| FOREIGN | FOREIGN | **No** | Fan-out risk |
| FOREIGN | PRIMARY | Yes | None |
| Any | NATURAL | Depends | May need dedup |

```python
def validate_join_safety(join: QueryPlanJoin) -> list[str]:
    """Return warnings for potentially unsafe joins."""
    warnings = []
    
    if join.left_entity and join.right_entity:
        left_type = join.left_entity.entity_type
        right_type = join.right_entity.entity_type
        
        # Foreign-to-foreign is dangerous (fan-out)
        if left_type == EntityType.FOREIGN and right_type == EntityType.FOREIGN:
            warnings.append(
                f"Fan-out risk: joining {join.left_table} to {join.right_table} "
                f"on foreign keys may multiply rows"
            )
            
        # Many-to-many explicit warning
        if join.cardinality == "many_to_many":
            warnings.append(
                f"Many-to-many join between {join.left_table} and {join.right_table} "
                f"- consider aggregating first"
            )
    
    return warnings
```

---

## 2. Dimension Types (Time vs Categorical)

### Current
```python
columns_selected: list[str] = []  # Just column names
```

### Enhanced
```python
class DimensionType(str, Enum):
    """Dimension types for grouping/filtering."""
    CATEGORICAL = "categorical"  # Non-numeric attributes (location, status, name)
    TIME = "time"                # Date/timestamp values
    NUMERIC = "numeric"          # Numeric values that could be dimensions (e.g., age buckets)


class TimeGranularity(str, Enum):
    """Time granularity options."""
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class QueryPlanDimension(BaseModel):
    """Describes a dimension (grouping column) in the query plan."""
    
    name: str                                    # Column name or alias
    source_column: Optional[str] = None          # Original column if transformed
    table: Optional[str] = None                  # Source table
    dimension_type: DimensionType = DimensionType.CATEGORICAL
    
    # Time-specific fields
    time_granularity: Optional[TimeGranularity] = None  # For time dimensions
    time_zone: Optional[str] = None                     # e.g., "UTC", "America/New_York"
    
    # Display
    label: Optional[str] = None                  # Human-readable label
    description: Optional[str] = None


class QueryPlan(BaseModel):
    # ... existing fields ...
    
    # ENHANCED: Typed dimensions instead of just column names
    dimensions: list[Union[QueryPlanDimension, str]] = []
    
    # Keep columns_selected for backwards compatibility
    columns_selected: list[str] = []  # Deprecated, use dimensions + measures
    
    # NEW: Default time dimension for the query
    primary_time_dimension: Optional[str] = None  # e.g., "block_time", "created_at"
    default_time_granularity: TimeGranularity = TimeGranularity.DAY
```

### Benefits

1. **Smart Time Handling**: LLM specifies granularity, SQL generator picks correct `date_trunc()`
2. **Validation**: Time dimensions must have valid granularity
3. **UI Hints**: Frontend can show date pickers for time dimensions

---

## 3. Measure Definitions (Structured Aggregations)

### Current
```python
class QueryPlanAggregation(BaseModel):
    function: Optional[str] = None  # "count", "sum", "avg", etc.
    column: Optional[str] = None
    alias: Optional[str] = None
    description: Optional[str] = None
```

### Enhanced
```python
class AggregationType(str, Enum):
    """Supported aggregation functions (aligned with MetricFlow)."""
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
    
    name: str                                    # Measure name/alias
    column: Optional[str] = None                 # Column being aggregated
    table: Optional[str] = None                  # Source table
    aggregation: AggregationType = AggregationType.SUM
    
    # For percentile aggregations
    percentile_value: Optional[float] = None     # e.g., 0.5 for median, 0.95 for p95
    
    # Filters specific to this measure
    measure_filter: Optional[str] = None         # e.g., "WHERE status = 'completed'"
    
    # Metadata
    label: Optional[str] = None                  # Display label
    description: Optional[str] = None
    unit: Optional[str] = None                   # e.g., "USD", "count", "percentage"
    
    # Lineage
    source: str = "inferred"  # "user_specified", "default", "inferred"


class QueryPlan(BaseModel):
    # ... existing fields ...
    
    # ENHANCED: Typed measures instead of generic aggregations
    measures: list[Union[QueryPlanMeasure, str]] = []
    
    # Keep aggregations for backwards compatibility
    aggregations: list[Union[QueryPlanAggregation, str]] = []  # Deprecated
```

---

## 4. Metric Types (Simple, Ratio, Cumulative, Derived)

### New Concept
```python
class MetricType(str, Enum):
    """
    Metric calculation types (from MetricFlow).
    Describes how the final metric is computed.
    """
    SIMPLE = "simple"           # Direct measure reference
    DERIVED = "derived"         # Expression combining other metrics
    RATIO = "ratio"             # One metric divided by another
    CUMULATIVE = "cumulative"   # Running total over time window
    CONVERSION = "conversion"   # Event conversion within time window


class QueryPlanMetric(BaseModel):
    """
    Describes the overall metric being computed.
    This is the "what" of the query at the highest level.
    """
    
    name: str                                # Metric name
    metric_type: MetricType = MetricType.SIMPLE
    
    # For SIMPLE metrics
    measure: Optional[str] = None            # Reference to a measure name
    
    # For RATIO metrics
    numerator: Optional[str] = None          # Measure or metric for numerator
    denominator: Optional[str] = None        # Measure or metric for denominator
    
    # For DERIVED metrics
    expression: Optional[str] = None         # e.g., "revenue - cost"
    component_metrics: list[str] = []        # Metrics used in expression
    
    # For CUMULATIVE metrics
    cumulative_window: Optional[str] = None  # e.g., "7 days", "1 month", "all time"
    
    # For CONVERSION metrics
    base_event: Optional[str] = None         # e.g., "page_view"
    conversion_event: Optional[str] = None   # e.g., "purchase"
    conversion_window: Optional[str] = None  # e.g., "7 days"
    
    # Metadata
    label: Optional[str] = None
    description: Optional[str] = None


class QueryPlan(BaseModel):
    # ... existing fields ...
    
    # NEW: Top-level metric definition
    metric: Optional[QueryPlanMetric] = None
```

### Examples

**Simple Metric**: Total Sales
```json
{
  "metric": {
    "name": "total_sales",
    "metric_type": "simple",
    "measure": "sales_amount"
  },
  "measures": [
    {"name": "sales_amount", "column": "amount", "aggregation": "sum"}
  ]
}
```

**Ratio Metric**: Conversion Rate
```json
{
  "metric": {
    "name": "conversion_rate",
    "metric_type": "ratio",
    "numerator": "conversions",
    "denominator": "visitors",
    "description": "Percentage of visitors who converted"
  },
  "measures": [
    {"name": "conversions", "column": "converted", "aggregation": "sum_boolean"},
    {"name": "visitors", "column": "visitor_id", "aggregation": "count_distinct"}
  ]
}
```

**Cumulative Metric**: 7-Day Rolling Revenue
```json
{
  "metric": {
    "name": "rolling_7d_revenue",
    "metric_type": "cumulative",
    "measure": "daily_revenue",
    "cumulative_window": "7 days"
  }
}
```

---

## Complete Enhanced QueryPlan

```python
class QueryPlan(BaseModel):
    """
    Human-readable query plan with semantic metadata.
    Combines our dynamic LLM approach with MetricFlow concepts.
    """
    
    model_config = {"extra": "allow"}
    
    # === Core Identity ===
    plan_summary: str = ""
    estimated_complexity: str = "moderate"
    reason_for_approval: Optional[str] = None
    
    # === Tables (Semantic Models) ===
    tables: list[str] = []
    primary_table: str = ""
    
    # === Joins with Entity Types ===
    joins: list[Union[QueryPlanJoin, str]] = []
    
    # === Dimensions (Grouping) ===
    dimensions: list[Union[QueryPlanDimension, str]] = []
    primary_time_dimension: Optional[str] = None
    default_time_granularity: TimeGranularity = TimeGranularity.DAY
    
    # === Measures (Aggregations) ===
    measures: list[Union[QueryPlanMeasure, str]] = []
    
    # === Metric (Top-Level Calculation) ===
    metric: Optional[QueryPlanMetric] = None
    
    # === Filters ===
    filters: list[Union[QueryPlanFilter, str]] = []
    
    # === Ordering & Limits ===
    order_by: list[str] = []
    limit: Optional[Union[int, str]] = None
    group_by: list[str] = []  # Often derived from dimensions
    
    # === Assumptions & Defaults ===
    assumptions: list[str] = []
    default_params: list[str] = []
    
    # === Schema Context ===
    relevant_schema: Optional[str] = None
    
    # === Backwards Compatibility (Deprecated) ===
    columns_selected: list[str] = []      # Use dimensions instead
    aggregations: list[Union[QueryPlanAggregation, str]] = []  # Use measures instead
```

---

## Validation Functions

```python
def validate_query_plan(plan: QueryPlan) -> ValidationResult:
    """Validate a query plan for safety and consistency."""
    errors = []
    warnings = []
    
    # 1. Join Safety
    for join in plan.joins:
        if isinstance(join, QueryPlanJoin):
            warnings.extend(validate_join_safety(join))
    
    # 2. Time Dimension Consistency
    if plan.primary_time_dimension:
        time_dims = [d for d in plan.dimensions 
                     if isinstance(d, QueryPlanDimension) 
                     and d.dimension_type == DimensionType.TIME]
        if not any(d.name == plan.primary_time_dimension for d in time_dims):
            warnings.append(
                f"Primary time dimension '{plan.primary_time_dimension}' "
                f"not found in dimensions list"
            )
    
    # 3. Metric Consistency
    if plan.metric:
        if plan.metric.metric_type == MetricType.RATIO:
            if not plan.metric.numerator or not plan.metric.denominator:
                errors.append("Ratio metric requires numerator and denominator")
        
        if plan.metric.metric_type == MetricType.CUMULATIVE:
            if not plan.primary_time_dimension:
                warnings.append(
                    "Cumulative metric without time dimension may produce "
                    "unexpected results"
                )
    
    # 4. Measure References
    measure_names = {m.name for m in plan.measures 
                     if isinstance(m, QueryPlanMeasure)}
    if plan.metric and plan.metric.measure:
        if plan.metric.measure not in measure_names:
            warnings.append(
                f"Metric references measure '{plan.metric.measure}' "
                f"not defined in measures list"
            )
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )
```

---

## Migration Path

### Phase 1: Add New Fields (Non-Breaking)
- Add all new optional fields to QueryPlan
- Existing plans continue to work
- LLM prompt updated to generate enhanced structure when possible

### Phase 2: LLM Prompt Enhancement
- Update query_planner prompt to request semantic metadata
- Provide examples of dimensions, measures, metrics
- Still accept simple string fallbacks

### Phase 3: Validation Integration
- Add join safety validation (warnings only initially)
- Surface warnings in plan approval UI
- Log validation results for analysis

### Phase 4: SQL Generation Enhancement
- Use dimension types for smart date_trunc()
- Use measure definitions for cleaner aggregations
- Use metric types for complex calculations (ratios, cumulative)

### Phase 5: Deprecation
- Mark old fields as deprecated in docs
- Continue supporting for backwards compatibility
- Gradually migrate historical plans

---

## Example: Full Enhanced Plan

User request: "Show me the 7-day rolling average of daily active users by country"

```json
{
  "plan_summary": "Calculate 7-day rolling average of daily active users, grouped by country",
  "estimated_complexity": "moderate",
  
  "tables": ["iceberg.analytics.user_activity", "iceberg.reference.countries"],
  "primary_table": "iceberg.analytics.user_activity",
  
  "joins": [
    {
      "left_table": "iceberg.analytics.user_activity",
      "right_table": "iceberg.reference.countries",
      "join_type": "left",
      "join_condition": "on country_code",
      "left_entity": {"name": "country", "column": "country_code", "entity_type": "foreign"},
      "right_entity": {"name": "country", "column": "code", "entity_type": "primary"},
      "cardinality": "many_to_one"
    }
  ],
  
  "dimensions": [
    {
      "name": "activity_date",
      "source_column": "activity_timestamp",
      "dimension_type": "time",
      "time_granularity": "day",
      "label": "Date"
    },
    {
      "name": "country_name",
      "source_column": "name",
      "table": "countries",
      "dimension_type": "categorical",
      "label": "Country"
    }
  ],
  "primary_time_dimension": "activity_date",
  "default_time_granularity": "day",
  
  "measures": [
    {
      "name": "daily_active_users",
      "column": "user_id",
      "aggregation": "count_distinct",
      "label": "DAU"
    }
  ],
  
  "metric": {
    "name": "rolling_7d_avg_dau",
    "metric_type": "cumulative",
    "measure": "daily_active_users",
    "cumulative_window": "7 days",
    "label": "7-Day Rolling Avg DAU",
    "description": "Average of daily active users over the past 7 days"
  },
  
  "filters": [
    {
      "column": "activity_date",
      "operator": ">=",
      "value": "30 days ago",
      "source": "default"
    }
  ],
  
  "order_by": ["activity_date ascending"],
  
  "assumptions": [
    "Using last 30 days of data for the rolling calculation",
    "DAU defined as distinct users with any activity"
  ]
}
```

This enhanced plan provides:
1. **Join safety**: We can validate the many-to-one join is safe
2. **Time intelligence**: SQL generator knows to use `date_trunc('day', activity_timestamp)`
3. **Clear measures**: DAU is explicitly count_distinct on user_id
4. **Metric type**: Cumulative metric tells SQL generator to use window function
