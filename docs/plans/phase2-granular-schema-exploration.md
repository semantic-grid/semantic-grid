# Phase 2: Granular Schema Exploration

## Overview

This phase implements on-demand, granular database schema exploration via a new `get_table_details` MCP tool. This allows the agent to:

1. First discover tables via lightweight `prompt_items_v2` (existing)
2. Then fetch detailed metadata for specific tables on-demand (new)

## Status: Phase 1 Complete

### Implemented Components

| Component | File | Status |
|-----------|------|--------|
| Pydantic models | `apps/db-meta/dbmeta_app/api/model.py` | Done |
| Introspection functions | `apps/db-meta/dbmeta_app/prompt_items/table_details.py` | Done |
| MCP tool | `apps/db-meta/dbmeta_app/api/routes.py` | Done |
| Cache TTL config | `apps/db-meta/dbmeta_app/cache/redis_cache.py` | Done |
| FM-APP client | `apps/fm-app/fm_app/mcp_servers/db_meta.py` | Done |
| Prompt formatter | `apps/fm-app/fm_app/mcp_servers/db_meta.py` | Done |

### Not Yet Implemented

| Component | Description | Priority |
|-----------|-------------|----------|
| Query planner integration | Call `get_table_details` after plan validation | Phase 2 |
| Prompt template update | Add `table_details` section to interactive_query prompt | Phase 2 |
| Unit tests | Test introspection functions with mock databases | Phase 2 |
| Integration tests | End-to-end flow with real db-meta | Phase 2 |

## Architecture

### Two-Phase Schema Exploration

```
Phase 1: Lightweight Discovery (existing)
┌─────────────────────────────────────────────────────────┐
│ prompt_items_v2(items=["DBStruct"], schema_top_k=10)    │
│ Returns: Table names, descriptions, column overview     │
│ Used by: Query Planner to select candidate tables       │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
Phase 2: Deep Table Details (NEW - implemented)
┌─────────────────────────────────────────────────────────┐
│ get_table_details(tables=["t1", "t2"], include=[...])   │
│ Returns: FK relationships, cardinality, value ranges    │
│ Used by: SQL Generator after plan is approved           │
└─────────────────────────────────────────────────────────┘
```

## API Reference

### Request Model

```python
class GetTableDetailsRequest(BaseModel):
    db: Optional[str] = None  # "wh", "wh_new", "wh_v2"
    tables: list[str]  # Fully qualified table names
    include: list[TableDetailsInclude] = [
        TableDetailsInclude.relationships,
        TableDetailsInclude.cardinality,
        TableDetailsInclude.ranges,
    ]
    cardinality_threshold: int = 100  # Max distinct values for "low cardinality"
    sample_size: int = 10000  # Rows to sample for stats
```

### Include Options

| Option | Description |
|--------|-------------|
| `relationships` | Primary keys and foreign key constraints |
| `cardinality` | Approximate distinct value counts per column |
| `low_cardinality_values` | Actual values for columns with few distinct values |
| `ranges` | Min/max values for numeric and date columns |
| `indexes` | Index information |

### Response Model

```python
class GetTableDetailsResponse(BaseModel):
    tables: list[TableDetails]
    content_hash: str  # For lineage tracking
    metadata: dict[str, Any]

class TableDetails(BaseModel):
    table_name: str
    description: Optional[str]
    row_count_estimate: Optional[int]
    primary_key: Optional[list[str]]
    foreign_keys: list[ForeignKeyInfo]
    indexes: list[IndexInfo]
    columns: list[ColumnDetails]

class ColumnDetails(BaseModel):
    name: str
    type: str
    nullable: bool
    description: Optional[str]
    example: Optional[str]
    is_primary_key: bool
    is_foreign_key: bool
    distinct_count: Optional[int]
    is_low_cardinality: Optional[bool]
    distinct_values: Optional[list[str]]
    min_value: Optional[str]
    max_value: Optional[str]
```

## Database Support

| Feature | ClickHouse | PostgreSQL | Trino | Others |
|---------|-----------|------------|-------|--------|
| Primary Keys | system.tables | SQLAlchemy inspector | N/A | SQLAlchemy |
| Foreign Keys | N/A | SQLAlchemy inspector | N/A | SQLAlchemy |
| Indexes | system.data_skipping_indices | SQLAlchemy inspector | N/A | SQLAlchemy |
| Row Count | system.tables.total_rows | pg_stat_user_tables | N/A | N/A |
| Cardinality | uniqExact + SAMPLE | pg_stats or COUNT(DISTINCT) | approx_distinct | COUNT(DISTINCT) |
| Ranges | MIN/MAX | MIN/MAX | MIN/MAX | MIN/MAX |

## Caching Strategy

```python
CACHE_TTL = {
    "table_details": 3600,       # 1 hour - stats can change
    "table_relationships": 86400, # 24 hours - PK/FK very stable
}
```

Cache key format: `dbmeta:table_details:{hash(profile, tables, include, threshold)}`

## FM-APP Client Usage

### Basic Usage

```python
from fm_app.mcp_servers.db_meta import (
    get_table_details_mcp,
    format_table_details_for_prompt,
)

# Fetch table details
result = await get_table_details_mcp(
    req=mcp_request,
    tables=["schema.table1", "schema.table2"],
    flow_step_num=step_num,
    settings=settings,
    logger=logger,
    include=["relationships", "cardinality", "ranges"],
)

# Format for LLM prompt
prompt_section = format_table_details_for_prompt(result)
```

### Formatted Output Example

```markdown
## Table Relationships & Statistics

### schema.wifi_sessions
_Stores WiFi session data for hotspots_

- **Estimated rows**: 1,608,837,646
- **Primary key**: session_id
- **Column statistics**:
  - **status**: ~5 distinct; values: ['active', 'completed', 'failed', 'timeout', 'cancelled']
  - **duration_seconds**: range: 0 to 86400
  - **event_timestamp**: range: 2020-01-01 to 2024-12-21
```

## Verification

### Linting

```bash
# db-meta (all pass)
cd apps/db-meta && uv run ruff check dbmeta_app/api/model.py dbmeta_app/api/routes.py dbmeta_app/prompt_items/table_details.py

# fm-app (all pass)
cd apps/fm-app && uv run ruff check fm_app/mcp_servers/db_meta.py
```

### Tests

```bash
# db-meta tests (30 passed, 1 skipped)
cd apps/db-meta && uv run pytest tests/ -v
```

### Import Verification

```bash
# db-meta
cd apps/db-meta && uv run python -c "from dbmeta_app.api.model import GetTableDetailsRequest; from dbmeta_app.prompt_items.table_details import get_table_details; print('OK')"

# fm-app
cd apps/fm-app && uv run python -c "from fm_app.mcp_servers.db_meta import get_table_details_mcp, format_table_details_for_prompt; print('OK')"
```

## Files Changed

### New Files

- `apps/db-meta/dbmeta_app/prompt_items/table_details.py` - Core introspection logic
- `docs/future/db-meta-v2-architecture.md` - Architecture vision document

### Modified Files

| File | Changes |
|------|---------|
| `apps/db-meta/dbmeta_app/api/model.py` | +87 lines: Added TableDetailsInclude, GetTableDetailsRequest, ForeignKeyInfo, ColumnDetails, IndexInfo, TableDetails, GetTableDetailsResponse |
| `apps/db-meta/dbmeta_app/api/routes.py` | +38 lines: Added `@mcp.tool() get_table_details()` |
| `apps/db-meta/dbmeta_app/cache/redis_cache.py` | +3 lines: Added TTL for table_details and table_relationships |
| `apps/fm-app/fm_app/mcp_servers/db_meta.py` | +253 lines: Added dataclasses, `get_table_details_mcp()`, `format_table_details_for_prompt()` |

## Next Steps

### Phase 2a: Query Planner Integration

1. Modify `apps/fm-app/fm_app/workers/interactive_flow/query_planner.py`:
   - After plan validation, before SQL generation
   - Call `get_table_details_mcp()` for plan tables
   - Store formatted details in query_plan context

2. Modify `apps/fm-app/fm_app/workers/interactive_flow/interactive_query.py`:
   - Include table_details in prompt variables
   - Pass to SQL generator

3. Update prompt template `packages/resources/fm_app/system-pack/v1.2.0/slots/interactive_query/prompt.md`:
   ```markdown
   {% if table_details %}
   {{ table_details }}
   {% endif %}
   ```

### Phase 2b: Testing

1. Add unit tests for `table_details.py`:
   - Mock database connections
   - Test each introspection function
   - Test caching behavior

2. Add integration test:
   - End-to-end flow with real db-meta
   - Verify MCP tool works correctly

## Backward Compatibility

All changes are additive:
- Existing MCP tools unchanged (`prompt_items_v2`, `preflight_query`, `validate_plan`)
- New `get_table_details` tool is optional
- FM-APP can use it or not
- No breaking changes to existing flows

## Related Documents

- `docs/future/db-meta-v2-architecture.md` - Long-term architecture vision
- `docs/future/db-meta-granular-schema-exploration.md` - Original detailed plan
- `docs/future/autonomous-agentic-flow.md` - FM-APP agent loop phases
