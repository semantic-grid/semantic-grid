# Multistep Flow Implementation Plan

## Status: Implemented

## Overview

Split the SQL generation flow into two steps with an optional user approval checkpoint:

1. **Query Planner** (new) - generates human-readable plan before SQL
2. **SQL Generation** (existing) - generates SQL based on approved plan

The intent analyzer assesses query complexity and decides if plan approval is required.

## Flow Diagram

```
User Request
    ↓
Intent Analyzer (planner slot)
    → IntentAnalysis { request_type, intent, summary, requires_plan_approval }
    ↓
    ├─ if requires_plan_approval = false → skip to SQL generation
    ↓
Query Planner (query_planner slot)
    → Status: Planning (transient)
    → QueryPlan { tables, joins, filters, assumptions, relevant_schema }
    → Status: FeedbackRequested (terminal)
    ↓
    ← User approves or provides feedback
    ↓ (loop until approved)
SQL Generation (interactive_query slot)
    → Uses relevant_schema from plan (reduced context)
    → QueryMetadata { sql, columns, ... }
    ↓
Response
```

## Request Status Flow

```
New → InProcess → Intent → Planning (transient, LLM generating plan)
                              ↓
                        FeedbackRequested (terminal, waiting for user)

[user responds with plan_approval]

New → InProcess → Intent → SQL → Finalizing → Done
```

## Context Strategy

**Planning step:**
- Full schema via `db_meta_prompt_items` + `db_ref_prompt_items`
- Outputs `QueryPlan` with `relevant_schema` field (subset of tables needed)

**SQL gen step:**
- **With plan:** Uses `relevant_schema` from plan (smaller context, faster)
- **Without plan:** Uses full MCP context (current behavior for simple queries)

This means complex queries pay the token cost upfront during planning, but SQL generation gets focused context. Simple queries work exactly as before.

## Implementation Details

### 1. Model Changes (`fm_app/api/model.py`)

#### RequestStatus
```python
class RequestStatus(str, Enum):
    new = "New"
    intent = "Intent"
    planning = "Planning"  # Transient: query plan is being generated
    feedback_requested = "FeedbackRequested"  # Terminal: awaiting user approval
    sql = "SQL"
    # ... rest unchanged
```

#### InteractiveRequestType
```python
class InteractiveRequestType(str, Enum):
    # ... existing types
    plan_approval = "plan_approval"  # User responding to a query plan
```

#### IntentAnalysis
```python
class IntentAnalysis(BaseModel):
    request_type: InteractiveRequestType
    intent: Optional[str] = None
    summary: Optional[str] = None
    response: Optional[str] = None
    requires_plan_approval: bool = False  # NEW
```

#### StructuredResponse
```python
class StructuredResponse(BaseModel):
    # ... existing fields
    query_plan: Optional[QueryPlan] = None  # NEW
```

#### QueryPlan Models
```python
class QueryPlanJoin(BaseModel):
    left_table: str
    right_table: str
    join_type: str  # "inner", "left", "right", "full", "cross"
    join_condition: str  # human-readable

class QueryPlanFilter(BaseModel):
    column: str
    operator: str
    value: str
    source: str = "inferred"  # "user_specified", "default", "inferred"

class QueryPlanAggregation(BaseModel):
    function: str
    column: str
    alias: str

class QueryPlan(BaseModel):
    tables: list[str]
    primary_table: str
    joins: list[QueryPlanJoin] = []
    columns_selected: list[str]
    filters: list[QueryPlanFilter] = []
    aggregations: list[QueryPlanAggregation] = []
    group_by: list[str] = []
    order_by: list[str] = []
    limit: Optional[int] = None
    assumptions: list[str] = []
    default_params: list[str] = []
    plan_summary: str
    estimated_complexity: str = "moderate"
    reason_for_approval: Optional[str] = None
    relevant_schema: Optional[str] = None  # Schema subset for SQL gen
```

### 2. Prompt Slots

#### `slots/planner/prompt.md` (Extended)
Added complexity assessment section that sets `requires_plan_approval` based on:
- Multiple tables / joins required
- Aggregations with grouping
- Temporal comparisons
- Ambiguous terms
- Analysis/comparison requests

#### `slots/query_planner/prompt.md` (New)
- Receives full MCP context (`db_meta_prompt_items`, `db_ref_prompt_items`)
- Outputs structured `QueryPlan`
- Extracts `relevant_schema` for tables used in plan
- Does NOT generate SQL

#### `slots/interactive_query/prompt.md` (Modified)
```jinja
{% if query_plan %}
## Approved Query Plan
{{ query_plan }}

## Relevant Database Schema
{{ relevant_schema }}
{% else %}
{{ db_meta_prompt_items }}
{{ db_ref_prompt_items }}
{% endif %}
```

### 3. Handlers

#### `query_planner.py` (New)
```python
async def generate_query_plan(ctx: FlowContext, intent: str) -> QueryPlan:
    # Build prompt variables
    # Render query_planner slot with MCP context
    # Call LLM with QueryPlan structured output
    # Trace: prompt_assembly, llm_call, errors
    # Return plan (orchestrator sets FeedbackRequested status)
```

#### `interactive_query.py` (Modified)
```python
async def handle_interactive_query(
    ctx: FlowContext,
    intent: IntentAnalysis,
    query_plan: Optional[QueryPlan] = None,  # NEW
) -> None:
    # If query_plan provided, add to prompt variables:
    #   - query_plan (JSON)
    #   - plan_summary
    #   - relevant_schema
```

#### `__init__.py` (Modified)
```python
# In intent routing:
if intent.requires_plan_approval:
    query_plan = await generate_query_plan(ctx, intent.intent)
    req.structured_response.query_plan = query_plan
    req.status = RequestStatus.feedback_requested
    await update_request_status(...)
    return req

# Handle plan_approval:
elif intent.request_type == InteractiveRequestType.plan_approval:
    query_plan = req.structured_response.query_plan if req.structured_response else None
    await handle_interactive_query(ctx, intent, query_plan=query_plan)
```

### 4. Observability

Query planner traces:
- `trace_prompt_assembly()` - slot rendering, lineage, MCP requirements
- `trace_llm_call()` - model, input/output, duration, tables, complexity
- `trace_error()` - if plan generation fails

All traces visible in admin traces endpoint alongside SQL generation traces.

## Files Changed

| File | Change |
|------|--------|
| `fm_app/api/model.py` | Added RequestStatus.planning, feedback_requested; InteractiveRequestType.plan_approval; QueryPlan models; requires_plan_approval field |
| `fm_app/workers/interactive_flow/__init__.py` | Plan step routing, FeedbackRequested status handling |
| `fm_app/workers/interactive_flow/query_planner.py` | New handler with full observability |
| `fm_app/workers/interactive_flow/interactive_query.py` | Accept optional query_plan parameter |
| `slots/planner/prompt.md` | Complexity assessment for requires_plan_approval |
| `slots/query_planner/prompt.md` | New slot for plan generation |
| `slots/query_planner/domain.md` | Placeholder for client overrides |
| `slots/interactive_query/prompt.md` | Conditional context based on plan |

## Rollback Strategy

Set `requires_plan_approval: false` in planner prompt instructions - flow falls back to direct SQL generation (existing behavior). No breaking changes to API.

## Frontend Integration Notes

Frontend needs to:
1. Detect `status: FeedbackRequested` with `query_plan` in response
2. Display plan in human-readable format (tables, joins, assumptions, summary)
3. Provide "Approve" / "Modify" actions
4. On approve: send new request with `request_type: plan_approval`
5. On modify: send feedback as regular request (goes through intent → regenerate plan)
