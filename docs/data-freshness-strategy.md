# Data Freshness Strategy

## Context

Queries are immutable objects (except for sorting/paging of results). The cache invalidation concern is about underlying warehouse data changing (new rows inserted, values updated) while cached results are still served.

Current behavior: Caches expire by TTL only (3 days for localStorage, configurable for Redis).

## Proposed Enhancements

### 1. Explicit User Refresh Signal

**Priority: High | Effort: Low**

Allow users to explicitly request fresh data, bypassing all cache layers.

**Implementation:**
- Add `force_refresh: boolean` param to SSE endpoint `/data/sse/:query_id`
- When true: skip Redis cache check, always execute query
- Invalidate frontend SWR/localStorage cache for that query_id
- Wire up to existing `onFetchData()` with a `forceRefresh` parameter
- Add refresh button to UI

**Flow:**
```
User clicks refresh
  → Frontend: invalidate SWR cache for query_id
  → Frontend: call SSE with force_refresh=true
  → Backend: skip Redis cache, execute fresh query
  → Backend: update Redis cache with new results
  → Frontend: receive fresh data
```

### 2. Data Freshness Metadata

**Priority: Medium | Effort: Low**

Return metadata alongside query results so users know what they're looking at.

**Implementation:**
- Add to SSE response metadata:
  - `fetched_at: ISO timestamp` - when data was fetched from warehouse
  - `cache_hit: boolean` - whether result came from cache
  - `data_age_seconds: number` - age of cached data
- Frontend displays freshness indicator (e.g., "cached 2h ago" vs "live")
- Could auto-suggest refresh if data exceeds threshold age

**Response structure:**
```json
{
  "rows": [...],
  "total_rows": 1000,
  "metadata": {
    "fetched_at": "2025-12-01T19:30:00Z",
    "cache_hit": true,
    "data_age_seconds": 7200
  }
}
```

### 3. LLM-Inferred `max_age`

**Priority: Low | Effort: Medium**

Let the LLM infer appropriate cache TTL based on query semantics.

**Implementation:**
- Add `max_age` to InteractiveQuery output schema
- LLM analyzes query to determine freshness needs:
  - "transactions in last 24h" → `max_age: 300` (5 min)
  - "all wallets onboarded since 2023" → `max_age: 86400` (1 day)
  - "historical token prices" → `max_age: 259200` (3 days)
- Pass `max_age` through to Redis cache TTL
- Frontend can use this to display "data as of X" and suggest refreshes

**Query analysis heuristics:**
- Time-relative filters (last N hours/days) → short TTL
- Date range filters ending "today" or "now" → medium TTL
- Historical/all-time queries → long TTL
- Aggregations over large time ranges → long TTL

## Recommended Implementation Order

1. **User refresh signal** - Quick win, gives users control
2. **Freshness metadata** - Low effort, adds transparency
3. **LLM max_age** - Nice-to-have automation, can be added later

## Related Files

**Frontend:**
- `apps/web/app/hooks/useInfiniteQuery.ts`
- `apps/web/app/contexts/DataFetchContext.tsx`
- `apps/web/app/contexts/QueryData/index.tsx`

**Backend:**
- `apps/fm-app/fm_app/api/routes.py` (SSE endpoint)
- `apps/fm-app/fm_app/cache/query_cache.py`
- `apps/fm-app/fm_app/workers/worker.py` (wrk_fetch_data task)
