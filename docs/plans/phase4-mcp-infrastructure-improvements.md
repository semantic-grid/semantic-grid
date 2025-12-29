# Phase 4: MCP Infrastructure Improvements

## Overview

This phase focuses on critical infrastructure improvements to the MCP (Model Context Protocol) integration between fm-app and db-meta:

1. **SSE → HTTP Transport Migration** - Modernize protocol for better reliability
2. **MCP Session Reuse** - Eliminate redundant sessions within a flow
3. **FastMCP 2.14 API Updates** - Fix breaking changes from upgrade

## Completed: December 2025

---

## Part 1: SSE → HTTP Transport Migration

### Problem

The original SSE (Server-Sent Events) transport had several limitations:
- Required two endpoints (`/sse` for events, `/sse/messages` for commands)
- Less suitable for stateless Kubernetes deployments
- Deprecated in favor of Streamable HTTP in MCP spec (March 2025)

### Solution

Migrate to Streamable HTTP transport:
- Single `/mcp` endpoint for all communication
- Full bidirectional JSON-RPC over HTTP
- Better suited for load-balanced environments

### Changes Made

#### db-meta Server

**File:** `apps/db-meta/dbmeta_app/main.py`
```python
# Before
mcp.run(transport="sse", host="0.0.0.0", port=settings.port)

# After
mcp.run(transport="http", host="0.0.0.0", port=settings.port)
```

#### fm-app Client

**File:** `apps/fm-app/fm_app/mcp_servers/db_meta.py`
```python
# Before (6 locations)
client = Client(f"{settings.dbmeta}sse")

# After
client = Client(f"{settings.dbmeta}mcp")
```

#### Dependency Upgrades

**Files:** `apps/fm-app/pyproject.toml`, `apps/db-meta/pyproject.toml`
```toml
"fastmcp>=2.14.0"      # Was 2.2.7
"pydantic>=2.12.2"     # Was 2.9.2
"pyjwt>=2.10.1"        # Was 2.9.0
"typing-extensions>=4.14.1"  # Was 4.12.2
"uvicorn>=0.35.0"      # Was 0.32.0
```

---

## Part 2: FastMCP 2.14 API Changes

### Problem

FastMCP 2.14 changed the `call_tool()` return type:
- Before: Returns `list[ContentBlock]` - accessed as `result[0].text`
- After: Returns `CallToolResult` object - accessed as `result.content[0].text`

### Changes Made

**File:** `apps/fm-app/fm_app/mcp_servers/db_meta.py`

All 6 MCP functions updated:
```python
# Before
result = await client.call_tool("tool_name", {...})
data = result[0].text

# After
result = await client.call_tool("tool_name", {...})
data = result.content[0].text
```

---

## Part 3: MCP Session Reuse

### Problem

Each MCP function was creating its own client session:
- 6+ MCP calls per flow = 6+ session negotiations
- Visible as multiple "Received session ID" in logs
- Each session ends with DELETE request (session termination)
- Unnecessary overhead and latency

### Solution

Implement session reuse at the flow level:

1. **Create client once** at flow initialization
2. **Pass client** to all MCP functions
3. **Single session** for entire flow duration

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ interactive_flow()                                          │
│                                                             │
│   ctx = initialize_flow()  ← Creates mcp_client            │
│                                                             │
│   async with ctx.mcp_client:  ← Opens ONE session          │
│       │                                                     │
│       ├── prompt_items_v2(client=ctx.mcp_client)           │
│       ├── validate_plan(client=ctx.mcp_client)             │
│       ├── get_table_details(client=ctx.mcp_client)         │
│       └── analyze_query(client=ctx.mcp_client)             │
│                                                             │
│   # Session closed here ← ONE DELETE request               │
└─────────────────────────────────────────────────────────────┘
```

### Key Implementation Detail

The `_use_client()` helper context manager handles both cases:

```python
@asynccontextmanager
async def _use_client(client: Optional[Client], settings):
    if client is not None:
        # Client provided - use directly (caller manages session)
        yield client
    else:
        # No client - create new session (backward compatible)
        new_client = create_db_meta_client(settings)
        async with new_client:
            yield new_client
```

This ensures:
- When client is passed: **No new session** - reuses existing
- When client is None: **Creates session** - backward compatible

### Changes Made

#### FlowContext

**File:** `apps/fm-app/fm_app/workers/interactive_flow/setup.py`
```python
@dataclass
class FlowContext:
    # ... existing fields ...
    mcp_client: Optional[Client] = field(default=None)  # NEW

async def initialize_flow(...):
    # Create MCP client for session reuse
    mcp_client = get_db_meta_client(settings)
    
    # Pass to async providers
    assembler.register_async_mcp(
        DbMetaAsyncProvider(settings, logger, client=mcp_client)
    )
    
    return FlowContext(..., mcp_client=mcp_client)
```

#### Flow Wrapper

**File:** `apps/fm-app/fm_app/workers/interactive_flow/__init__.py`
```python
async def interactive_flow(...):
    ctx = await initialize_flow(...)
    
    # Single session for entire flow
    async with ctx.mcp_client:
        return await _execute_flow(ctx, req)
```

#### MCP Functions

**File:** `apps/fm-app/fm_app/mcp_servers/db_meta.py`

All functions now accept optional `client` parameter:
```python
async def get_db_meta_mcp_prompt_items_v2(
    req, flow_step_num, settings, logger,
    items=None, schema_top_k=10, examples_top_k=5,
    client: Optional[Client] = None,  # NEW
):
    async with _use_client(client, settings) as _client:
        result = await _client.call_tool(...)
```

#### Async Providers

**File:** `apps/fm-app/fm_app/mcp_servers/mcp_async_providers.py`
```python
class DbMetaAsyncProvider:
    def __init__(self, settings, logger, client: Optional[Client] = None):
        self.client = client  # Store for reuse
    
    async def vars_for_slot(self, ...):
        result = await get_db_meta_mcp_prompt_items_v2(
            ..., client=self.client  # Pass through
        )
```

---

## Part 4: Async Event Loop & SQLAlchemy Connection Pool Fix

### Problem

Celery workers showed multiple issues:
1. Deprecation warning: `There is no current event loop`
2. Runtime error: `Event loop is closed`
3. Runtime error: `Future attached to a different loop` (asyncpg/SQLAlchemy)
4. **Connection exhaustion**: PostgreSQL connections not being released over time

The root cause: SQLAlchemy async engine was created at **module load time** with whatever event loop existed then. But each Celery task creates a **new event loop**, causing:
- Connection pool tied to wrong/dead loop
- Connections never properly returned to pool
- "Future attached to different loop" errors
- Gradual connection leak until pool exhaustion

### Solution

**1. Per-Loop Engine Registry** - Create SQLAlchemy engines lazily, bound to current event loop:

**File:** `apps/fm-app/fm_app/workers/db_session.py`
```python
# Before - module-level engine (bound to import-time loop)
engine = create_async_engine(DATABASE_URL, ...)
SESSION = sessionmaker(bind=engine, ...)

# After - per-loop engine registry
_engine_registry: dict[int, tuple[AsyncEngine, sessionmaker]] = {}

async def _get_engine_for_current_loop():
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    
    if loop_id not in _engine_registry:
        # Create engine bound to THIS loop
        engine = create_async_engine(DATABASE_URL, ...)
        session_factory = sessionmaker(bind=engine, ...)
        _engine_registry[loop_id] = (engine, session_factory)
    
    return _engine_registry[loop_id]

async def dispose_engine_for_current_loop():
    """Call when event loop is about to close - releases connections."""
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    if loop_id in _engine_registry:
        engine, _ = _engine_registry.pop(loop_id)
        await engine.dispose()  # Returns connections to pool
```

**2. Proper Task Cleanup** - Dispose engine before closing loop:

**File:** `apps/fm-app/fm_app/workers/worker.py`
```python
@app.task(name="wrk_add_request")
def wrk_add_request(args):
    from fm_app.workers.db_session import dispose_engine_for_current_loop
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_wrk_add_request(args))
    finally:
        # Dispose engine to release connections BEFORE closing loop
        try:
            loop.run_until_complete(dispose_engine_for_current_loop())
        except Exception:
            pass  # Best effort
        loop.close()
```

**3. Same pattern for notification tasks:**

**File:** `apps/fm-app/fm_app/workers/tasks/notify.py`
```python
from fm_app.workers.db_session import get_db, dispose_engine_for_current_loop

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    summary = loop.run_until_complete(fetch_summary())
    loop.run_until_complete(dispose_engine_for_current_loop())
finally:
    loop.close()
```

### Why This Fixes Connection Exhaustion

Before:
- Engine created at import → bound to initial loop
- Task creates new loop → engine operations fail or leak
- Connections never returned → pool grows until exhausted

After:
- Engine created per-loop → properly bound
- `dispose_engine_for_current_loop()` called before loop closes
- `engine.dispose()` returns all connections to pool
- No leaks, proper cleanup

### Important Note

**Do NOT cache MCP clients across Celery tasks** - each task creates a new event loop, and clients from previous loops will fail with "Future attached to a different loop" error.

---

## Part 5: Deprecation Fixes

### Pydantic Query Pattern

**File:** `apps/fm-app/fm_app/api/routes.py`
```python
# Before
sort_order: str = Query("asc", regex="^(asc|desc)$")

# After
sort_order: str = Query("asc", pattern="^(asc|desc)$")
```

### FastAPI Lifespan

**File:** `apps/fm-app/fm_app/__init__.py`
```python
# Before
@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()

# After
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()

app = FastAPI(..., lifespan=lifespan)
```

---

## Results

### Before Phase 4
```
Received session ID: abc123
HTTP Request: DELETE .../mcp
Received session ID: def456
HTTP Request: DELETE .../mcp
Received session ID: ghi789
HTTP Request: DELETE .../mcp
... (6+ sessions per flow)
```

### After Phase 4
```
Received session ID: abc123
... (all MCP calls reuse session)
HTTP Request: DELETE .../mcp
(1 session per flow)
```

### Benefits

1. **Reduced latency** - No repeated session negotiation
2. **Cleaner logs** - Single session ID per flow
3. **Modern protocol** - HTTP transport is MCP standard
4. **No deprecation warnings** - Clean startup
5. **Backward compatible** - Functions work with or without shared client

---

## Files Modified

| File | Changes |
|------|---------|
| `apps/db-meta/pyproject.toml` | Dependency upgrades |
| `apps/db-meta/dbmeta_app/main.py` | `transport="http"` |
| `apps/fm-app/pyproject.toml` | Dependency upgrades |
| `apps/fm-app/fm_app/mcp_servers/db_meta.py` | API fix, session reuse, `_use_client()` helper |
| `apps/fm-app/fm_app/mcp_servers/mcp_async_providers.py` | Accept/pass client |
| `apps/fm-app/fm_app/workers/interactive_flow/setup.py` | Add mcp_client to FlowContext |
| `apps/fm-app/fm_app/workers/interactive_flow/__init__.py` | Wrap flow in client session |
| `apps/fm-app/fm_app/workers/interactive_flow/query_planner.py` | Pass client |
| `apps/fm-app/fm_app/workers/interactive_flow/discovery.py` | Pass client |
| `apps/fm-app/fm_app/workers/interactive_flow/manual_query.py` | Pass client |
| `apps/fm-app/fm_app/workers/interactive_flow/interactive_query.py` | Pass client |
| `apps/fm-app/fm_app/workers/worker.py` | Event loop fix |
| `apps/fm-app/fm_app/api/routes.py` | `regex` → `pattern` |
| `apps/fm-app/fm_app/__init__.py` | Lifespan context manager |

---

## Related Documents

- `docs/plans/mcp-http-transport-migration.md` - Original migration plan
- `docs/plans/phase2-granular-schema-exploration.md` - `get_table_details` implementation
- `docs/plans/phase3-plan-driven-schema-fetch.md` - Schema fetch after plan approval
