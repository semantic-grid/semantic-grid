# Query Plan as First-Class Entity

## Overview

Promote QueryPlan from embedded JSONB in `request.query_plan` to a dedicated `query_plan` table with parent-child lineage, mirroring the existing `query` table pattern.

## Core Principle

**Every query has a plan** — no exceptions.

```
Intent → Plan → Query
```

- Complex requests: Plan → [user approval] → Query
- Simple requests: Plan → [auto-approve] → Query

This ensures uniform lineage and consistent data model regardless of the flow path.

## Entity Relationships

```
Session
  │
  ├── Request A: "show me top wallets"
  │     └── creates: Plan P1
  │
  ├── Request B: "add volume column"
  │     └── creates: Plan P2 (parent_id = P1)
  │
  ├── Request C: "approved"
  │     └── creates: Query Q1 (plan_id = P2)
  │
  ├── Request D: "filter to ETH only"
  │     └── creates: Plan P3
  │
  └── Request E: "approved"
        └── creates: Query Q2 (plan_id = P3, parent_id = Q1)
```

### Key Relationships

| From | To | Via | Purpose |
|------|----|-----|---------|
| Plan | Parent Plan | `query_plan.parent_id` | Amendment chain |
| Query | Plan | `query.plan_id` | Which plan produced this query |
| Query | Parent Query | `query.parent_id` | Query refinement chain |
| Plan | Request | `query_plan.request_id` | Which request created this plan |
| Plan | Session | `query_plan.session_id` | Session context (denormalized) |

### Linked Query Context

When processing a linked query (refining Q1):
1. Get Q1 via `query.parent_id`
2. Get P2 (plan that produced Q1) via `query.plan_id`
3. Use P2's structure/intent as context for new plan generation

## Database Schema

### New Table: `query_plan`

```sql
CREATE TABLE query_plan (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    plan_id UUID NOT NULL DEFAULT gen_random_uuid(),
    
    -- Relationships
    session_id UUID NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
    request_id UUID NOT NULL REFERENCES request(request_id) ON DELETE CASCADE,
    parent_id UUID REFERENCES query_plan(plan_id) ON DELETE SET NULL,
    
    -- Plan content
    tables JSONB DEFAULT '[]',
    primary_table VARCHAR,
    joins JSONB DEFAULT '[]',
    columns_selected JSONB DEFAULT '[]',
    filters JSONB DEFAULT '[]',
    aggregations JSONB DEFAULT '[]',
    group_by JSONB DEFAULT '[]',
    order_by JSONB DEFAULT '[]',
    plan_limit VARCHAR,
    assumptions JSONB DEFAULT '[]',
    default_params JSONB DEFAULT '[]',
    plan_summary TEXT NOT NULL,
    estimated_complexity VARCHAR DEFAULT 'moderate',
    reason_for_approval TEXT,
    relevant_schema TEXT,
    
    -- Intent tracking
    original_intent TEXT NOT NULL,
    amendment_feedback TEXT,  -- user feedback that triggered this iteration (null for first plan)
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    PRIMARY KEY (plan_id)
);

-- Indexes
CREATE INDEX idx_query_plan_plan_id ON query_plan(plan_id);
CREATE INDEX idx_query_plan_session_id ON query_plan(session_id);
CREATE INDEX idx_query_plan_request_id ON query_plan(request_id);
CREATE INDEX idx_query_plan_parent_id ON query_plan(parent_id);
```

### Modification to `query` Table

```sql
ALTER TABLE query ADD COLUMN plan_id UUID REFERENCES query_plan(plan_id);
CREATE INDEX idx_query_plan_id ON query(plan_id);
```

## No Status Field

Plan status is derived from relationships:

| Condition | Derived Status |
|-----------|----------------|
| Has child plan (`parent_id` points to it) | Amended |
| Linked from a query (`query.plan_id`) | Executed |
| No child, no query link | Pending or Abandoned |

We don't need to distinguish "pending" from "abandoned" — both are simply plans that were never executed.

## Flow Changes

### Planning Phase (all requests)

```python
async def generate_query_plan(..., parent_plan_id=None, amendment_feedback=None):
    # 1. Generate plan via LLM
    plan = await llm_generate_plan(...)
    
    # 2. Save to query_plan table
    plan_record = await create_query_plan(
        session_id=session_id,
        request_id=request_id,
        parent_id=parent_plan_id,
        original_intent=intent,
        amendment_feedback=amendment_feedback,
        **plan.dict()
    )
    
    # 3. Also write to request.query_plan JSONB (dual-write for backward compat)
    await update_request_query_plan(request_id, plan.dict())
    
    return plan, plan_record.plan_id
```

### Plan Approval

```python
async def handle_plan_approval(session_id, request_id):
    # 1. Get the latest plan for this session
    plan = await get_latest_plan_for_session(session_id)
    
    # 2. Generate SQL using plan
    query = await generate_and_execute_sql(plan)
    
    # 3. Link query to plan
    await update_query_plan_id(query.query_id, plan.plan_id)
```

### Plan Amendment

```python
async def handle_plan_amendment(session_id, request_id, feedback):
    # 1. Get the previous plan
    previous_plan = await get_latest_plan_for_session(session_id)
    
    # 2. Generate new plan with parent context
    new_plan, new_plan_id = await generate_query_plan(
        ...,
        parent_plan_id=previous_plan.plan_id,
        amendment_feedback=feedback
    )
```

### Linked Query (Refinement)

```python
async def handle_linked_query(parent_query_id, new_intent):
    # 1. Get parent query and its plan
    parent_query = await get_query(parent_query_id)
    parent_plan = await get_query_plan(parent_query.plan_id)
    
    # 2. Generate new plan with parent query/plan context
    new_plan = await generate_query_plan(
        ...,
        context={
            "parent_query": parent_query,
            "parent_plan": parent_plan
        }
    )
```

## Migration Strategy

### Phase 1: Add New Infrastructure (Non-Breaking)
1. Create `query_plan` table
2. Add `plan_id` column to `query` table
3. Create CRUD operations in `query_plan_db.py`

### Phase 2: Dual-Write
1. Write to new `query_plan` table (primary)
2. Also write to `request.query_plan` JSONB (legacy)
3. Read from new table, fallback to JSONB

### Phase 3: Historical Migration (Optional)
```sql
-- Migrate existing request.query_plan JSONB to query_plan table
INSERT INTO query_plan (session_id, request_id, original_intent, plan_summary, ...)
SELECT 
    r.session_id,
    r.request_id,
    r.request as original_intent,
    r.query_plan->>'plan_summary' as plan_summary,
    ...
FROM request r
WHERE r.query_plan IS NOT NULL;

-- Link existing queries to migrated plans
UPDATE query q
SET plan_id = qp.plan_id
FROM query_plan qp
WHERE q.request_id = qp.request_id;
```

### Phase 4: Cleanup (Future)
- Remove `request.query_plan` JSONB column
- Remove dual-write logic

## Files to Create/Modify

| File | Action |
|------|--------|
| `alembic/versions/xxx_add_query_plan_table.py` | NEW - Migration |
| `fm_app/api/model.py` | ADD - Pydantic models |
| `fm_app/db/query_plan_db.py` | NEW - CRUD operations |
| `fm_app/workers/interactive_flow/query_planner.py` | MODIFY - Save to DB |
| `fm_app/workers/interactive_flow/__init__.py` | MODIFY - Read from DB |

## Storage Considerations

### `relevant_schema` Field
Can be 10-100KB. Options:
- Start simple: store as-is
- If storage grows: compress, or store hash and retrieve from MCP on demand

### LLM Context for Amendments
Include only essential fields from parent plan:
- `plan_summary`
- `tables`, `filters`, `assumptions`
- `amendment_feedback`

Exclude `relevant_schema` from amendment context (re-fetch if needed).

## Benefits

1. **Better amendment context** — Full plan structure, not combined strings
2. **Clear lineage** — Intent → Plan → Query (always)
3. **Analytics** — Query patterns by plan structure, amendment rates
4. **Consistency** — Same model for complex and simple requests
5. **Debugging** — Can always trace back from query to plan to intent
