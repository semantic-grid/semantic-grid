# MCP HTTP Transport Migration Plan

## Overview

Migrate db-meta MCP server from SSE transport to Streamable HTTP transport.

**Benefits:**
- Single `/mcp` endpoint (simpler than `/sse` + `/sse/messages`)
- Full bidirectional communication
- Better suited for stateless deployments
- Industry standard (recommended by MCP spec since March 2025)

---

## Current State

### db-meta (Server)
```python
# main.py:62
mcp.run(transport="sse", host="0.0.0.0", port=settings.port)
```
- Endpoint: `/sse`
- FastMCP version: 2.14.1 (already upgraded)

### fm-app (Client)
```python
# fm_app/mcp_servers/db_meta.py (6 locations)
client = Client(f"""{settings.dbmeta}sse""")
```
- Config: `DBMETA="http://dbmeta:8080"` → `http://dbmeta:8080/sse`
- FastMCP version: needs upgrade

---

## Migration Steps

### Phase 1: Upgrade fm-app Dependencies

**File:** `apps/fm-app/pyproject.toml`

```diff
- "fastmcp==X.X.X",
+ "fastmcp>=2.14.0",
```

Also update related dependencies if needed:
- `pydantic>=2.12.2`
- `uvicorn>=0.35.0`
- `pyjwt>=2.10.1`
- `typing-extensions>=4.14.1`

Run:
```bash
cd apps/fm-app && uv lock && uv sync
```

### Phase 2: Update fm-app Client URLs

**File:** `apps/fm-app/fm_app/mcp_servers/db_meta.py`

Change all 6 occurrences:
```diff
- client = Client(f"""{settings.dbmeta}sse""")
+ client = Client(f"""{settings.dbmeta}mcp""")
```

Lines: 62, 119, 184, 253, 395, 570

### Phase 3: Update db-meta Server Transport

**File:** `apps/db-meta/dbmeta_app/main.py`

```diff
- mcp.run(transport="sse", host="0.0.0.0", port=settings.port)
+ mcp.run(transport="http", host="0.0.0.0", port=settings.port)
```

### Phase 4: Coordinated Deployment

**Important:** Both changes must be deployed together since `/sse` won't exist after db-meta switches to HTTP transport.

**Deployment order:**
1. Deploy fm-app with updated client URLs (pointing to `/mcp`)
   - Will fail until db-meta is updated, but that's expected
2. Deploy db-meta with HTTP transport
   - Now fm-app can connect

**Or use feature flag approach:**
1. Add env var to db-meta to control transport
2. Deploy db-meta with both transports possible
3. Update fm-app
4. Switch db-meta to HTTP via env var

---

## Rollback Plan

If issues occur:
1. Revert db-meta to `transport="sse"`
2. Revert fm-app to `{settings.dbmeta}sse`
3. Redeploy both

---

## Testing Checklist

- [ ] fm-app dependencies updated and locked
- [ ] Local test: db-meta with HTTP transport starts correctly
- [ ] Local test: fm-app connects to db-meta `/mcp` endpoint
- [ ] Local test: `prompt_items_v2` tool call works
- [ ] Local test: `preflight_query` tool call works
- [ ] Local test: `validate_plan` tool call works
- [ ] Local test: `get_table_details` tool call works
- [ ] Staging deployment successful
- [ ] Production deployment successful

---

## Files to Modify

| File | Change |
|------|--------|
| `apps/fm-app/pyproject.toml` | Upgrade fastmcp + dependencies |
| `apps/fm-app/fm_app/mcp_servers/db_meta.py` | Change `/sse` → `/mcp` (6 places) |
| `apps/db-meta/dbmeta_app/main.py` | Change `transport="sse"` → `transport="http"` |

---

## Optional: Environment Variable Control

For gradual rollout, add transport selection via env var:

**db-meta config.py:**
```python
mcp_transport: str = "sse"  # or "http"
```

**db-meta main.py:**
```python
mcp.run(transport=settings.mcp_transport, host="0.0.0.0", port=settings.port)
```

**fm-app config.py:**
```python
dbmeta_endpoint: str = "sse"  # or "mcp"
```

**fm-app db_meta.py:**
```python
client = Client(f"{settings.dbmeta}{settings.dbmeta_endpoint}")
```

This allows switching without code changes.

---

## Cleanup

After successful migration:
1. Remove `run_http.py` test file from db-meta
2. Remove `tests/test_http_transport.py` or move to proper test suite
3. Update documentation references from `/sse` to `/mcp`
