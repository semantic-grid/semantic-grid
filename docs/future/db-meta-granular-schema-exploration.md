# DB-Meta Granular Schema Exploration - Implementation Plan

## Overview

Enhance db-meta MCP server to support granular, on-demand database exploration where:
1. Agent planning phase selects table candidates (lightweight)
2. Agent requests detailed metadata for specific tables (rich, on-demand)

**Key Principle**: Backward compatible - existing tools continue to work unchanged.

---

## Current State

### Existing MCP Tools (must remain unchanged):
- `prompt_items_v2` - Returns schema + examples + instructions
- `preflight_query` - Validates SQL syntax
- `validate_plan` - Checks tables/columns exist
- `get_database_overview` - Discovery/help

### Current Schema Depth:
- Table names + descriptions
- Column names, types, nullable, defaults
- Human descriptions from YAML
- Sample values from YAML

### Missing (to be added):
- PK-FK relationships
- Column cardinality + distinct values
- Min/max ranges for numeric/date columns
- Index information

---

## Proposed Architecture

### Two-Phase Schema Exploration:

```
Phase 1: Lightweight Discovery (existing behavior)
┌─────────────────────────────────────────────────────────┐
│ prompt_items_v2(items=["DBStruct"], schema_top_k=10)    │
│ Returns: Table names, descriptions, column overview     │
│ Used by: Query Planner to select candidate tables       │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
Phase 2: Deep Table Details (NEW)
┌─────────────────────────────────────────────────────────┐
│ get_table_details(tables=["t1", "t2"], include=[...])   │
│ Returns: FK relationships, cardinality, value ranges    │
│ Used by: SQL Generator after plan is approved           │
└─────────────────────────────────────────────────────────┘
```

---

## New MCP Tool: `get_table_details`

### Request Model:
```python
class GetTableDetailsRequest(BaseModel):
    db: str  # "wh", "new_wh", "wh_v2"
    tables: list[str]  # Fully qualified table names
    include: list[str] = ["relationships", "cardinality", "ranges"]
    # Options:
    #   "relationships" - PK-FK constraints
    #   "cardinality" - Distinct value counts
    #   "low_cardinality_values" - Actual values for low-cardinality columns
    #   "ranges" - Min/max for numeric/date columns
    #   "indexes" - Index information
    cardinality_threshold: int = 100  # Max distinct values to fetch
    sample_size: int = 10000  # Rows to sample for stats
```

### Response Model:
```python
class TableDetails(BaseModel):
    table_name: str
    primary_key: list[str] | None
    foreign_keys: list[ForeignKeyInfo]
    columns: list[ColumnDetails]

class ForeignKeyInfo(BaseModel):
    columns: list[str]
    referred_table: str
    referred_columns: list[str]

class ColumnDetails(BaseModel):
    name: str
    type: str
    nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    # New fields:
    distinct_count: int | None  # Approximate cardinality
    is_low_cardinality: bool  # distinct_count < threshold
    distinct_values: list[str] | None  # If low cardinality
    min_value: str | None  # For numeric/date
    max_value: str | None

class GetTableDetailsResponse(BaseModel):
    tables: list[TableDetails]
    content_hash: str
    metadata: dict
```

---

## YAML Configuration Extensions

### Mark columns for special handling:
```yaml
profiles:
  wh_v2:
    tables:
      iceberg.radius.wifi_sessions:
        columns:
          status:
            low_cardinality: true  # Fetch distinct values
            cardinality_limit: 50  # Override default threshold
          event_timestamp:
            stats: true  # Fetch min/max
          nas_identifier:
            stats: false  # Skip stats (too many values)
```

### Default behavior (no YAML config):
- Auto-detect low cardinality: `COUNT(DISTINCT) < 100`
- Auto-fetch ranges for: `timestamp`, `date`, `int`, `float` types
- Skip stats for: `text`, `varchar(>256)`, `blob` types

---

## Implementation Steps

### Step 1: Database Introspection Enhancements (db-meta)

**File: `apps/db-meta/dbmeta_app/prompt_items/db_struct.py`**

Add functions:
```python
async def get_primary_keys(engine, table_name, schema) -> list[str]
async def get_foreign_keys(engine, table_name, schema) -> list[ForeignKeyInfo]
async def get_column_cardinality(engine, table_name, column, sample_size) -> int
async def get_column_distinct_values(engine, table_name, column, limit) -> list[str]
async def get_column_range(engine, table_name, column) -> tuple[Any, Any]
```

Database-specific implementations:
- **ClickHouse**: Use system.columns for stats, SAMPLE for cardinality
- **PostgreSQL**: Use pg_stats for pre-computed stats
- **Trino**: Use ANALYZE stats if available, else sample

### Step 2: New MCP Tool (db-meta)

**File: `apps/db-meta/dbmeta_app/api/routes.py`**

```python
@mcp.tool()
async def get_table_details(req: GetTableDetailsRequest) -> GetTableDetailsResponse:
    """Get detailed metadata for specific tables including relationships and stats."""
    ...
```

### Step 3: Caching Layer (db-meta)

**File: `apps/db-meta/dbmeta_app/cache/redis_cache.py`**

- Cache key: `table_details:{db}:{table_name}:{include_hash}`
- TTL: 1 hour for stats, 24 hours for relationships
- Invalidation: Manual refresh endpoint

### Step 4: fm-app Integration

**File: `apps/fm-app/fm_app/mcp_servers/db_meta.py`**

Add function:
```python
async def get_table_details_mcp(
    tables: list[str],
    db: str,
    include: list[str] = ["relationships", "cardinality", "ranges"]
) -> TableDetailsResult:
    ...
```

### Step 5: Query Planner Integration

**File: `apps/fm-app/fm_app/workers/interactive_flow/query_planner.py`**

After plan validation, before SQL generation:
```python
if query_plan.tables:
    table_details = await get_table_details_mcp(
        tables=query_plan.tables,
        db=db_name,
        include=["relationships", "low_cardinality_values", "ranges"]
    )
    # Store in query_plan.table_details for SQL generator
```

### Step 6: SQL Generator Integration

**File: `apps/fm-app/fm_app/workers/interactive_flow/interactive_query.py`**

Inject table details into prompt:
```python
if query_plan and query_plan.table_details:
    interactive_query_vars["table_details"] = format_table_details(query_plan.table_details)
```

### Step 7: Prompt Template Updates

**File: `packages/resources/fm_app/system-pack/v1.2.0/slots/interactive_query/prompt.md`**

Add section:
```markdown
{% if table_details %}
## Table Relationships & Statistics

{{ table_details }}
{% endif %}
```

---

## Backward Compatibility Guarantees

1. **Existing tools unchanged**: `prompt_items_v2`, `preflight_query`, `validate_plan` keep same signatures
2. **New tool is additive**: `get_table_details` is a new tool, not a replacement
3. **YAML config optional**: Existing YAML files work without changes
4. **Graceful degradation**: If stats unavailable, return `null` instead of error
5. **fm-app fallback**: If `get_table_details` fails, continue with existing flow

---

## Performance Considerations

1. **On-demand only**: Stats fetched only for selected tables, not all tables
2. **Sampling**: Use SAMPLE/TABLESAMPLE for large tables
3. **Caching**: Cache stats in Redis (1hr TTL for stats, 24hr for relationships)
4. **Parallel fetching**: Fetch stats for multiple tables concurrently
5. **Timeout**: 10s timeout per table, skip if exceeded

---

## Files to Modify

### db-meta (apps/db-meta/):
- `dbmeta_app/api/model.py` - Add new Pydantic models
- `dbmeta_app/api/routes.py` - Add `get_table_details` MCP tool
- `dbmeta_app/prompt_items/db_struct.py` - Add introspection functions
- `dbmeta_app/cache/redis_cache.py` - Add caching for table details

### fm-app (apps/fm-app/):
- `fm_app/mcp_servers/db_meta.py` - Add `get_table_details_mcp()` function
- `fm_app/api/model.py` - Add TableDetails to QueryPlan model
- `fm_app/workers/interactive_flow/query_planner.py` - Fetch details after plan validation
- `fm_app/workers/interactive_flow/interactive_query.py` - Include details in SQL generation

### Resources (packages/resources/):
- `fm_app/system-pack/v1.2.0/slots/interactive_query/prompt.md` - Add table details section

---

## Testing Strategy

1. **Unit tests**: New introspection functions with mock databases
2. **Integration tests**: End-to-end flow with real db-meta
3. **Backward compat tests**: Existing flows still work without changes
4. **Performance tests**: Verify stats collection completes within timeout

---

## Rollout Plan

1. **Phase 1**: Add `get_table_details` tool to db-meta (no fm-app changes)
2. **Phase 2**: Add fm-app client function (optional usage)
3. **Phase 3**: Integrate into query planner (behind feature flag)
4. **Phase 4**: Enable by default after validation
