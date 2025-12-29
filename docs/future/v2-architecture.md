# Semantic Grid v2 Architecture

## Overview

This document outlines the proposed v2 architecture for Semantic Grid, featuring a redesigned separation of concerns between fm-app and db-meta, built on PydanticAI and leveraging MCP's sampling and elicitation capabilities.

## Vision

### Core Principles

1. **fm-app-v2** becomes a specialized AI agent for databases and UI grids
2. **fm-app-v2** should be swappable with any MCP-compatible AI agent (Claude Desktop, ChatGPT, etc.) - core functionality preserved, UX degraded without specialized grid support
3. **db-meta-v2** becomes the centerpiece of database semantics and intelligence, exposed via MCP
4. **db-meta-v2** owns UI features (grid specs, chart suggestions) exposed via MCP
5. **db-meta-v2** is pluggable alongside other MCP servers

### Responsibility Split

| Component | Owns | Artifacts |
|-----------|------|-----------|
| **fm-app-v2** | Users, sessions, messages, specialized grid UX | Conversations, user preferences |
| **db-meta-v2** | Database semantics, query intelligence, UI specs | Tasks, plans, queries, grid configs |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AI Agents (Interchangeable)                 │
├─────────────────┬─────────────────┬─────────────────┬───────────────┤
│   fm-app-v2     │  Claude Desktop │    ChatGPT      │   Other MCP   │
│  (specialized)  │   (generic)     │   (generic)     │    Clients    │
├─────────────────┴─────────────────┴─────────────────┴───────────────┤
│                              MCP Protocol                           │
├─────────────────────────────────────────────────────────────────────┤
│                           db-meta-v2                                │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐      │
│  │   Tools      │  Resources   │   Prompts    │   UI Specs   │      │
│  │ (planning,   │ (schema,     │ (templates)  │ (grid specs) │      │
│  │  querying)   │  examples)   │              │              │      │
│  └──────────────┴──────────────┴──────────────┴──────────────┘      │
│                                                                     │
│  Artifact Flow: Task → Plan → Query → Result → UI Spec             │
└─────────────────────────────────────────────────────────────────────┘
```

## MCP Features Leveraged

### Sampling (Server-Initiated LLM Calls)

Sampling allows MCP servers to request LLM completions through the client. This enables db-meta-v2 to:

- Generate query plans using the client's LLM
- Generate SQL using the client's LLM
- Remain model-agnostic (client chooses the model)

**Flow:**
1. Server sends `sampling/createMessage` request to client
2. Client reviews/modifies the request (human-in-the-loop)
3. Client calls its LLM
4. Client returns result to server

**Key:** Sampling is transport-agnostic - works over both stdio and Streamable HTTP.

### Elicitation (Server-Initiated User Input)

Elicitation allows servers to request structured input from users:

- Plan approval ("Should I use these tables?")
- Clarification ("Which time range?")
- Confirmation ("Execute this query?")

**Limitations:**
- Only primitive types supported (string, number, boolean, enum)
- Complex approvals may need custom UI in fm-app-v2

### References

- [MCP Sampling Specification](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)
- [MCP Elicitation Specification](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)
- [MCP Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) - confirms sampling/elicitation are transport-agnostic

## Technology Stack: PydanticAI

### Why PydanticAI?

PydanticAI is a Python agent framework from the Pydantic team with:

- **Model-agnostic** - OpenAI, Anthropic, Gemini, custom providers
- **Type-safe** - Full IDE support, `Agent[DepsType, OutputType]`
- **Structured outputs** - Pydantic models as output types, auto-validated
- **Native MCP support** - Both as client and server
- **Dependency injection** - `RunContext[DepsType]` for type-safe deps
- **Graph workflows** - `pydantic-graph` for state machines
- **Durability** - Temporal integration for production

### MCP Integration

**As MCP Client (fm-app-v2):**
```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP

db_meta = MCPServerStreamableHTTP('http://localhost:8000/mcp')
agent = Agent('anthropic:claude-sonnet', toolsets=[db_meta])

async with db_meta:
    result = await agent.run('Show me top wallets by volume')
```

**As MCP Server with Sampling (db-meta-v2):**
```python
from fastmcp import FastMCP
from pydantic_ai import Agent
from pydantic_ai.models.mcp_sampling import MCPSamplingModel

server = FastMCP('db-meta')
planner = Agent(MCPSamplingModel(), output_type=QueryPlan)

@server.tool()
async def generate_query_plan(intent: str, schema: str) -> QueryPlan:
    # Uses CLIENT's LLM via MCP sampling
    result = await planner.run(f"Plan: {intent}\nSchema: {schema}")
    return result.output
```

### References

- [PydanticAI Documentation](https://ai.pydantic.dev/)
- [PydanticAI MCP Client](https://ai.pydantic.dev/mcp/client/)
- [PydanticAI MCP Server](https://ai.pydantic.dev/mcp/server/)
- [PydanticAI Graph](https://ai.pydantic.dev/graph/)
- [PydanticAI Temporal Integration](https://ai.pydantic.dev/durable_execution/temporal/)

## Proposed Query Flow (v2)

```
User: "Calculate average offload traffic for LA"
         │
         ▼
┌─────────────────┐
│   fm-app-v2     │  Manages session, routes to db-meta
└────────┬────────┘
         │ MCP: call tool "get_intent"
         ▼
┌─────────────────┐
│   db-meta-v2    │  Determines intent, available tools
└────────┬────────┘
         │ MCP Sampling: "Generate query plan"
         ▼
┌─────────────────┐
│   LLM (client)  │  Returns structured QueryPlan
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   db-meta-v2    │  Validates plan against schema
└────────┬────────┘
         │ MCP Elicitation: "Approve this plan?"
         ▼
┌─────────────────┐
│   User (client) │  YES / NO / Modify
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   db-meta-v2    │  Enriches plan with detailed schema
└────────┬────────┘
         │ MCP Sampling: "Generate SQL"
         ▼
┌─────────────────┐
│   LLM (client)  │  Returns SQL + metadata
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   db-meta-v2    │  Validates SQL (EXPLAIN), repairs if needed
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   db-meta-v2    │  Executes query, generates UI spec
└────────┬────────┘
         │ Returns: QueryResult + UISpec
         ▼
┌─────────────────┐
│   fm-app-v2     │  Renders specialized grid UI
└─────────────────┘
```

## Monorepo Structure (v2 alongside v1)

```
apps/
├── fm-app/              # v1 - current FastAPI + Celery
├── fm-app-v2/           # v2 - PydanticAI agent (NEW)
├── db-meta/             # v1 - current FastMCP server
├── db-meta-v2/          # v2 - MCP server with sampling (NEW)
├── web/                 # frontend (works with both)
└── cms/                 # unchanged

packages/
├── resources/           # shared prompt packs
├── client-configs/      # shared tenant configs
└── sg-models/           # NEW: shared Pydantic models
    ├── pyproject.toml
    └── src/sg_models/
        ├── task.py      # Task, TaskStatus
        ├── plan.py      # QueryPlan, PlanValidation
        ├── query.py     # QueryResult, QueryMetadata
        └── ui.py        # GridSpec, ColumnSpec, ChartSpec
```

## Implementation Decisions

### 1. Build Order

**Start with db-meta-v2.**

- It's the "brain" of the new architecture
- Can be tested with Claude Desktop before fm-app-v2 exists
- Forces correct MCP interface design
- fm-app-v2 becomes simpler once db-meta-v2's contract is defined

**Validation:** Connect Claude Desktop to db-meta-v2, generate SQL through natural language.

### 2. Shared Models Package

**Yes - `packages/sg-models`**

Both apps import shared Pydantic models:
- `QueryPlan`, `PlanValidation`
- `QueryResult`, `QueryMetadata`
- `GridSpec`, `ColumnSpec`, `ChartSpec`

This ensures db-meta-v2 and fm-app-v2 speak the same language.

### 3. API Compatibility

**New API contract, coexisting with v1.**

- fm-app-v2 exposes `/api/v2/` prefix
- Web frontend feature-flags between v1 and v2
- v2 API can be WebSocket-first for streaming
- Eventually sunset v1 routes

### 4. Task Durability

**Start with pydantic-graph, design for Temporal.**

- pydantic-graph is built-in, zero infrastructure
- Good enough for dev/testing
- Design state/nodes to be Temporal-compatible
- Add Temporal when needed: multi-day workflows, crash recovery, distributed execution

Key: Keep nodes/state serializable from day one.

## Swappable Agent Test

When a generic client (Claude Desktop) connects to db-meta-v2:

| Works | Degraded |
|-------|----------|
| Natural language → SQL | No specialized grid rendering |
| Query planning with approval | Generic text/JSON output |
| Schema exploration | No interactive refinement UI |
| Validation and repair | No session persistence |

The **core value** (semantic query generation) lives in db-meta-v2.
The **UX enhancement** lives in fm-app-v2.

## UI Specification (MCP-UI)

db-meta-v2 returns UI specs alongside query results:

```python
{
    "sql": "SELECT ...",
    "data": [...],
    "ui": {
        "type": "datagrid",
        "columns": [
            {"field": "wallet", "type": "address", "formatter": "ethereum"},
            {"field": "balance", "type": "currency", "decimals": 2},
            {"field": "last_active", "type": "datetime", "relative": True}
        ],
        "default_sort": {"field": "balance", "direction": "desc"},
        "grouping": {"enabled": True, "fields": ["chain"]},
        "chart_suggestion": {"type": "bar", "x": "chain", "y": "balance"}
    }
}
```

- **fm-app-v2** interprets UI spec → renders MUI X Data Grid Pro
- **Generic clients** ignore UI spec → show raw data/JSON

## Frontend Protocol: AG-UI

### Why AG-UI?

AG-UI (Agent-User Interaction Protocol) is an open standard from CopilotKit that standardizes how frontend applications communicate with AI agents. It's event-based and designed for streaming state changes - exactly what db-meta-v2 produces.

### The Streaming Model

db-meta-v2's `get_data` tool streams state changes throughout execution:

```
get_data called
  ├── state: "planning"
  ├── state: "plan_ready", plan: {...}
  ├── elicitation: "approve plan?"
  ├── state: "generating_sql"
  ├── state: "validating"
  ├── state: "repairing" (if needed)
  ├── state: "executing"
  └── state: "complete", result: {...}, ui_spec: {...}
```

AG-UI's event types map directly to this:
- `STATE_SNAPSHOT` / `STATE_DELTA` - Progress updates
- `TOOL_CALL_START` / `TOOL_CALL_END` - Tool execution visibility
- Human-in-the-loop interrupts for plan approval

### AG-UI vs Vercel AI SDK

| Aspect | AG-UI | Vercel AI SDK |
|--------|-------|---------------|
| **Design focus** | Agent workflows with state | Chat conversations |
| **State sync** | Native bi-directional (`STATE_DELTA`) | Manual implementation |
| **Event streaming** | Full event protocol | Token streaming |
| **Human-in-the-loop** | Built-in interrupt/resume | `addToolApprovalResponse` |
| **PydanticAI support** | `AGUIAdapter` | `VercelAIAdapter` |
| **Current web app** | Would need adoption | Already installed (`ai` package) |

**Verdict:** AG-UI is the better fit because:
1. State streaming is native, not bolted on
2. Designed for workflow-heavy agents, not just chat
3. Plan approval maps to built-in interrupt pattern
4. PydanticAI has first-class support via `AGUIAdapter`

### Frontend Implementation

```tsx
import { useAgent } from '@copilotkit/react-core';

interface QueryState {
  status: 'idle' | 'planning' | 'awaiting_approval' | 'generating' | 'validating' | 'executing' | 'complete';
  plan?: QueryPlan;
  query?: string;
  result?: QueryResult;
  uiSpec?: GridSpec;
}

function QueryWorkspace() {
  const { state, sendMessage } = useAgent<QueryState>({
    url: '/api/v2/agent',
    initialState: { status: 'idle' }
  });

  return (
    <Box>
      <ChatInput onSend={sendMessage} />
      
      {/* Reactive status - updates automatically as state streams */}
      <QueryStatus status={state.status} />
      
      {/* Plan approval appears when state.status === 'awaiting_approval' */}
      {state.status === 'awaiting_approval' && (
        <PlanApproval plan={state.plan} />
      )}
      
      {/* Grid renders when complete */}
      {state.status === 'complete' && (
        <DataGridPro 
          rows={state.result.data}
          columns={mapUiSpecToColumns(state.uiSpec)}
        />
      )}
    </Box>
  );
}
```

The key: **state flows from agent → UI automatically** via the event stream. No polling, no manual WebSocket wiring.

### Backend Integration (fm-app-v2)

PydanticAI's `AGUIAdapter` handles the protocol:

```python
from pydantic_ai.ui import AGUIAdapter

adapter = AGUIAdapter(agent)

# Starlette/FastAPI endpoint
@app.post("/api/v2/agent")
async def agent_endpoint(request: Request):
    return await adapter.dispatch_request(request)
```

### References

- [AG-UI Protocol](https://docs.ag-ui.com/)
- [AG-UI Overview (CopilotKit)](https://www.copilotkit.ai/ag-ui)
- [PydanticAI AG-UI Integration](https://ai.pydantic.dev/ui/ag-ui/)
- [CopilotKit useAgent Hook](https://www.marktechpost.com/2025/12/11/copilotkit-v1-50-brings-ag-ui-agents-directly-into-your-app-with-the-new-useagent-hook/)

## db-meta-v2 MCP Interface

### Design Principles

1. **Encapsulate complexity** - Clients see simple tools, not internal implementation
2. **Defense in depth** - Read-only enforced at DB level AND validation layer
3. **Cost-aware execution** - Tiered guardrails prevent DB overload
4. **Canonical queries** - SQL normalized to AST, deduplicated by UUID, efficiently cached

### Tools

Three entry points, one unified output: **Result + UISpec**.

| Tool | Input | Entry Point | Description |
|------|-------|-------------|-------------|
| `get_data` | `intent: str` | Natural language | Full flow: NL → Plan → SQL → Result |
| `run_sql` | `sql: str` | SQL statement | Skip NL/planning, same safety layer |
| `get_result` | `query_uuid: str` | Canonical UUID | Fetch cached or execute stored query |

```
┌─────────────────────────────────────────────────────────────┐
│                      db-meta-v2 Tools                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  get_data(intent) ──→ NL → Plan → SQL ─┐                   │
│                                         │                   │
│  run_sql(sql) ────────────────→ SQL ───┤                   │
│                                         ▼                   │
│                                   ┌───────────┐             │
│                                   │Canonicalize│            │
│                                   │  → UUID    │            │
│                                   └─────┬─────┘             │
│                                         │                   │
│  get_result(uuid) ──────────────────────┤                   │
│                                         ▼                   │
│                                   ┌───────────┐             │
│                                   │Cache hit? │             │
│                                   └─────┬─────┘             │
│                                    yes/ \no                 │
│                                      /   \                  │
│                                     ▼     ▼                 │
│                                  Return  Safety Layer       │
│                                     \     ↓                 │
│                                      \   Execute            │
│                                       \   ↓                 │
│                                        ▼                    │
│                                    Result + UISpec          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Shared Safety Layer

All three tools converge through the same safety layer:

```
┌─────────────────────────────────────────────────────────────┐
│                   Shared Safety Layer                       │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │   Validate   │ → │  Read-only   │ → │ Canonicalize │    │
│  │  (EXPLAIN)   │   │    check     │   │   → UUID     │    │
│  └──────────────┘   └──────────────┘   └──────────────┘    │
│                                               │             │
│                                               ▼             │
│                                        ┌──────────────┐     │
│                                        │ Cache lookup │     │
│                                        └──────┬───────┘     │
│                                          hit/ \miss         │
│                                            /   \            │
│                                           ▼     ▼           │
│                                       Return   Cost Tier    │
│                                               Analysis      │
│                                                  │          │
│                              ┌───────────────────┼────────┐ │
│                              ▼                   ▼        ▼ │
│                           [AUTO]            [CONFIRM] [REJECT]
│                              │                   │        │ │
│                              ▼                   ▼        ▼ │
│                          Execute            Elicit    Error │
│                              │              approval       │ │
│                              │                   │          │
│                              └───────┬───────────┘          │
│                                      ▼                      │
│                               Result + UISpec               │
└─────────────────────────────────────────────────────────────┘
```

### Read-Only Enforcement

Defense in depth - multiple layers ensure no mutations:

1. **DB connection level** - Read-only user/role (primary enforcement)
2. **Validation layer** - Parse and reject non-SELECT statements
3. **EXPLAIN analysis** - Catch anything that slipped through

### Query Cost Tiers

Prevents DB overload by categorizing queries before execution:

| Tier | Criteria | Action |
|------|----------|--------|
| **Auto** | Cache hit, OR (cost < threshold AND rows < limit) | Execute immediately |
| **Confirm** | Cost/rows exceed soft limits, within hard limits | Elicit: "Query scans ~2M rows. Execute?" |
| **Reject** | Exceeds hard limits, likely to timeout | Return error + suggestion to narrow scope |

Cache hits always bypass cost checks - they're free.

### Canonicalization

SQL text is normalized to a canonical AST, producing a deterministic UUID:

```
SQL text → Parse → Normalize AST → Serialize → SHA256 → UUID
```

Normalization handles:
- Whitespace differences
- Alias naming variations
- Column order (when semantically equivalent)
- Comment stripping
- Literal format normalization

Two semantically identical queries get the same UUID, enabling efficient caching and deduplication.

### Storage Model

```
┌─────────────────────────────────────────────────────────────┐
│                     Query Store                             │
│                                                             │
│  query_uuid (PK) │ canonical_sql │ original_sql │ metadata │
│  ────────────────┼───────────────┼──────────────┼──────────│
│  abc123...       │ SELECT ...    │ SELECT ...   │ {...}    │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Result Cache                            │
│                                                             │
│  Tiered: Memory (L1) → Redis (L2) → Persistent (L3)        │
│                                                             │
│  Key: query_uuid                                            │
│  Value: result data, ui_spec, timestamp, ttl               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

- **Query Store**: Persists canonical queries (UUID → SQL mapping)
- **Result Cache**: Caches execution results, tiered by hotness

### Resources

Read-only data clients can fetch for context:

| Resource | URI Pattern | Description |
|----------|-------------|-------------|
| `schema://overview` | Schema overview | Tables, descriptions, domains |
| `schema://tables/{table}` | Table details | Columns, types, relationships |
| `queries://popular` | Popular queries | Most used queries by usage count |
| `queries://featured` | Featured queries | Curated/promoted queries |
| `queries://search?q={query}` | Semantic search | Find similar existing queries |
| `queries://tagged/{tag}` | Tagged queries | Queries by domain/category |
| `cache://stats` | Cache statistics | Hit rates, popular queries |

### Prompts

Reusable prompt templates - both internal and user-facing:

**Internal prompts (used by tools):**

| Prompt | Arguments | Description |
|--------|-----------|-------------|
| `plan_query` | `intent`, `schema` | Generate query plan from intent |
| `generate_sql` | `plan`, `schema` | Generate SQL from approved plan |
| `repair_sql` | `sql`, `error` | Fix SQL based on validation error |

**User-facing prompts (slash commands):**

Curated queries exposed as MCP prompts, surfaced as slash commands in clients:

| Prompt | Slash Command | Description |
|--------|---------------|-------------|
| `top_wallets` | `/top-wallets` | Show top wallets by balance |
| `daily_volume` | `/daily-volume` | Daily transaction volume |
| `whale_activity` | `/whale-activity` | Recent whale movements |

These are dynamically generated from featured queries in the query store.

### Semantic Query Matching

Before generating a new query, `get_data` searches for semantically similar existing queries:

```
User: "show me wallet activity"
                │
                ▼
        ┌───────────────┐
        │Semantic search│
        │ via embedding │
        └───────┬───────┘
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
   [Matches]       [No matches]
        │               │
        ▼               ▼
   Suggest to      Generate new
   reuse existing  (full flow)
```

**Query Store with Embeddings:**

```
┌─────────────────────────────────────────────────────────────┐
│                     Query Store                             │
│                                                             │
│  query_uuid │ canonical_sql │ embedding │ metadata          │
│  ───────────┼───────────────┼───────────┼──────────────────│
│  abc123     │ SELECT ...    │ [0.1,...] │ {                │
│             │               │           │   intent: "...", │
│             │               │           │   usage_count: N,│
│             │               │           │   last_used: ts, │
│             │               │           │   tags: [...],   │
│             │               │           │   featured: bool,│
│             │               │           │   slug: "..."    │
│             │               │           │ }                │
└─────────────────────────────────────────────────────────────┘
```

**Flow when matches found:**

```python
# In get_data, before planning
matches = await query_store.semantic_search(intent, limit=5)

if matches and matches[0].score > SIMILARITY_THRESHOLD:
    yield StateEvent(
        status="match_found",
        matches=[{
            "uuid": m.uuid,
            "intent": m.metadata.intent,
            "score": m.score,
            "usage_count": m.metadata.usage_count
        } for m in matches[:3]]
    )
    
    # Elicit: use existing or generate new?
    choice = await ctx.elicit(
        QueryChoiceSchema,
        message="Found similar queries. Use existing or generate new?"
    )
    
    if choice.use_existing:
        await query_store.increment_usage(choice.selected_uuid)
        yield from get_result(choice.selected_uuid)
        return

# No match or user wants new - proceed with generation
yield StateEvent(status="planning")
```

**Benefits:**

1. **Faster results** - Reuse cached queries instead of regenerating
2. **Consistency** - Same question gets same answer
3. **Discovery** - Users find queries they didn't know existed
4. **Usage analytics** - Track which queries are valuable
5. **Slash commands** - Featured queries become one-click actions

## Open Questions

1. **Multi-tenant in db-meta-v2:** How does client/env routing work when db-meta-v2 is called from generic MCP clients?

2. **Prompt template migration:** How do we migrate the slot/overlay system to db-meta-v2? Does it own templates, or fetch from shared resources?

3. **Authentication:** How do generic MCP clients authenticate to db-meta-v2?

4. **Cache invalidation:** Time-based TTL only, or schema-change triggered?

## Next Steps

1. [ ] Scaffold `apps/db-meta-v2` with FastMCP + PydanticAI
2. [ ] Create `packages/sg-models` with core Pydantic models
3. [ ] Implement first tool: `generate_query_plan` with sampling
4. [ ] Test with Claude Desktop
5. [ ] Add validation and repair loop
6. [ ] Implement UI spec generation
7. [ ] Scaffold `apps/fm-app-v2` as thin PydanticAI agent
8. [ ] Connect fm-app-v2 to db-meta-v2
9. [ ] Feature-flag in web frontend

---

*Document created: 2024-12-29*
*Based on architecture discussion and MCP/PydanticAI research*
