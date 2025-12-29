# Phase 3: Plan-Driven Schema Fetch

## Problem Statement

The current flow has a critical gap:

1. **RAG selects top-k tables** for the prompt (e.g., top 10)
2. **Planner selects the correct table** (e.g., `cdr_agg_day`) based on domain knowledge
3. **BUT**: If the correct table wasn't in top-k, its schema is missing from the prompt
4. **SQL Generator hallucinates column names** → query fails

### Example Failure

```
User: "list top 10 hotspots by traffic"

RAG selection (top 10): [daily_stats_cdrs, hh_agg_day, wifi_sessions, ...] 
                        ❌ cdr_agg_day NOT included (ranked #11)

Planner output:
  - Table: cdr_agg_day ✅ (correct choice!)
  - Columns needed: "hotspot identifier", "traffic volume"

SQL Generator:
  - Has NO schema for cdr_agg_day
  - Guesses: SELECT hotspot_id, total_bytes ... ❌ WRONG
  - Actual columns: agw_sn/telco_id, total_volume

Result: Query fails with "column not found"
```

## Solution: Plan-Driven Schema Fetch

Use the planner's table selection to fetch schemas **after** plan approval, **before** SQL generation.

### New Flow

```
┌─────────────────────────────────────────────────────────┐
│ Phase 1: Planning (lightweight)                         │
│                                                         │
│   Prompt contains:                                      │
│   - Domain model (business context)                     │
│   - Table names + descriptions (all tables, no columns) │
│   - Examples                                            │
│                                                         │
│   Planner outputs:                                      │
│   - Selected tables: ["cdr_agg_day"]                    │
│   - Semantic column descriptions                        │
│   - Filters, aggregations, etc.                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
                    [User Approves Plan]
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 2: Schema Fetch (NEW STEP)                        │
│                                                         │
│   get_table_details(tables=["cdr_agg_day"])             │
│                                                         │
│   Returns:                                              │
│   - Full column names and types                         │
│   - Column descriptions                                 │
│   - PK/FK relationships                                 │
│   - Value ranges, cardinality                           │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 3: SQL Generation (precise)                       │
│                                                         │
│   Prompt contains:                                      │
│   - Approved plan (what to build)                       │
│   - Full schema for selected tables (how to build)     │
│   - Examples                                            │
│                                                         │
│   SQL Generator:                                        │
│   - Maps "traffic volume" → total_volume ✅             │
│   - Maps "hotspot id" → agw_sn/telco_id ✅             │
│   - Generates correct SQL                               │
└─────────────────────────────────────────────────────────┘
```

## Key Insight

**Separation of concerns:**

| Phase | Needs | Doesn't Need |
|-------|-------|--------------|
| Planning | Table purposes, domain context | Exact column names |
| SQL Generation | Exact column names, types | All tables in DB |

The planner works at the **semantic level** ("I need traffic data per hotspot").
The SQL generator works at the **syntactic level** ("Use `total_volume` from `cdr_agg_day`").

## Implementation

### Prerequisites (Done in Phase 2)

- [x] `get_table_details` MCP tool in db-meta
- [x] `get_table_details_mcp()` client in fm-app
- [x] `format_table_details_for_prompt()` formatter

### Phase 3 Tasks

#### 1. Modify Planning Phase Prompt

File: `packages/resources/fm_app/system-pack/v1.2.0/slots/planner/prompt.md`

Change `prompt_items_v2` call:
- Keep: `DomainModel`, `Instruction`, `Examples`
- Modify: `DBStruct` → lightweight version (table names + descriptions only)

Or simply increase `schema_top_k` to include more tables in planning, relying on Phase 2 to provide precise schema later.

#### 2. Add Schema Fetch After Plan Approval

File: `apps/fm-app/fm_app/workers/interactive_flow/query_planner.py` (or equivalent)

```python
async def process_approved_plan(plan: QueryPlan, context: FlowContext):
    # Plan is approved, now fetch full schema for selected tables
    if plan.tables:
        table_details = await get_table_details_mcp(
            req=context.mcp_request,
            tables=plan.tables,
            flow_step_num=context.step_num,
            settings=context.settings,
            logger=context.logger,
            include=["relationships", "low_cardinality_values", "ranges"],
        )
        context.table_details = format_table_details_for_prompt(table_details)
    
    # Continue to SQL generation with enriched context
    return await generate_sql(plan, context)
```

#### 3. Update SQL Generation Prompt

File: `packages/resources/fm_app/system-pack/v1.2.0/slots/interactive_query/prompt.md`

```markdown
## Approved Query Plan

{{ query_plan }}

{% if table_details %}
## Table Schema Details

{{ table_details }}
{% endif %}

## Your Task

Generate SQL that implements the approved plan using the exact column names from the schema above.
```

#### 4. Pass table_details Through Flow

Ensure `table_details` is passed from the plan approval step to the SQL generation step via flow context or state.

## Benefits

1. **No more hallucinated columns** - SQL gen always has correct schema
2. **Planner can select any table** - not limited by RAG top-k
3. **Reduced planning prompt size** - no need for full schemas in planning
4. **Better separation of concerns** - planning is semantic, SQL gen is syntactic
5. **Backward compatible** - existing flow works, this is an enhancement

## Testing Plan

### Unit Tests

1. Test `get_table_details_mcp()` returns correct schema
2. Test `format_table_details_for_prompt()` output format
3. Test plan parsing extracts table names correctly

### Integration Tests

1. Query that requires table outside RAG top-10
2. Verify schema is fetched for plan's tables
3. Verify SQL uses correct column names

### Manual Testing

1. "list top 10 hotspots by traffic" → should use `cdr_agg_day.total_volume`
2. "list 1000 entries in iceberg table" → should use actual `wifi_qm_v2` columns

## Rollout

1. **Feature flag**: `ENABLE_PLAN_DRIVEN_SCHEMA_FETCH=true`
2. **A/B test**: Compare SQL error rates with/without
3. **Gradual rollout**: Start with specific clients/envs

## Related Documents

- `docs/plans/phase2-granular-schema-exploration.md` - Phase 2 implementation
- `docs/future/schema-relevance-hybrid-search.md` - BM25 + vector hybrid search
