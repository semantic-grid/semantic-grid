# Data Context Refactor

## Overview

Consolidate data fetching and state management into a unified `DataContext` with a reusable `QueryDataGrid` wrapper component.

## Current Architecture (Problems)

Data-related logic is spread across multiple locations:

| Concern | Current Location |
|---------|------------------|
| SSE subscriptions | `DataFetchContext` |
| SWR cache config | `swr-provider.tsx` |
| LocalStorage cache | `localStorageProvider.ts` |
| Query state | `GridSession`, `QueryData` |
| Fetch handlers | `GridSession`, `QueryData` |
| Button/overlay logic | `table.tsx` (duplicated in `/grid` and `/q`) |

## Proposed Architecture

### DataContext

Global context for data state management.

```typescript
interface QueryState {
  status: 'idle' | 'pending' | 'success' | 'error';
  rows: any[];
  totalRows: number;
  error?: string;
  cachedAt?: number;  // timestamp
  ttl?: number;       // from query max_age
}

interface DataContextValue {
  queryStates: Map<string, QueryState>;
  fetchQuery: (queryId: string, options?: { notify?: boolean; force?: boolean }) => void;
  cancelFetch: (queryId: string) => void;
  isStale: (queryId: string) => boolean;
  getQueryData: (queryId: string) => QueryState | undefined;
}
```

**Responsibilities:**
- SSE connection management
- Request deduplication
- Cache management (SWR + localStorage)
- Query state tracking per query_id
- Fetch/cancel operations

### QueryDataGrid Component

Reusable wrapper that handles all data display states.

```typescript
interface QueryDataGridProps {
  queryId: string;
  sql: string;
  columns: GridColDef[];
  performanceWarning?: boolean;
  sortModel?: GridSortItem[];
  onSortModelChange?: (model: GridSortItem[]) => void;
}
```

**Responsibilities:**
- Read state from DataContext
- Render appropriate overlay based on state
- Render MUI DataGrid with data
- Handle footer buttons

## UI State Machine

### State Table

| State | Center | Data Area | Footer |
|-------|--------|-----------|--------|
| No cache, no pending, no warning | Fetch button | - | - |
| No cache, no pending, has warning | Fetch & Notify button | - | - |
| No cache, pending | Spinner + Cancel | - | - |
| Has cache, fresh | - | Data | Refresh OR Refresh & Notify |
| Has cache, stale, no warning | Spinner overlay | Data | Refresh + Cancel |
| Has cache, stale, has warning | Refresh button | Data | Refresh & Notify |
| Fetch error | Error + Retry | - | - |

### State Flow Diagram

```
Component Load
      │
      ▼
Has cached data? ──No──► Is data fetch pending?
      │                        │
     Yes                      Yes──► Show spinner + Cancel
      │                        │
      ▼                       No
Is data fresh?                 │
      │                        ▼
     Yes                 No performance warning?
      │                   │              │
      │                  Yes            No
      │                   │              │
      │                   ▼              ▼
      │            Show Fetch      Show Fetch &
      │            button          Notify button
      │             (center)         (center)
      │                   │              │
      │                   └──────┬───────┘
      │                          │
      │                          ▼ (button clicked)
      │                   Show spinner + Cancel
      │                          │
      ▼                          ▼
Show data ◄──────────── No fetch error?
      │                          │
      │                         No
      │                          │
      │                          ▼
      │                    Show Error + Retry
      │
      ▼
Cache (update) data
```

### Footer Buttons

Always visible when data exists:
- **No warning:** "Refresh" button
- **Has warning:** "Refresh & Notify" button
- **During fetch:** Show "Cancel" button additionally

Footer buttons trigger **force refresh** (bypass cache).

## Data Freshness

### Current
- TTL-based: 3 days for localStorage cache

### Future Enhancement
- `max_age` from LLM InteractiveQuery output
- Query-specific TTL based on query semantics
- See `docs/future/data-freshness-strategy.md`

## Implementation Steps

### Phase 1: DataContext
1. Create `DataContext` with query state management
2. Move SSE subscription logic from `DataFetchContext`
3. Integrate with SWR cache
4. Add `fetchQuery`, `cancelFetch`, `isStale` methods

### Phase 2: QueryDataGrid
1. Create `QueryDataGrid` component
2. Implement state machine for overlays
3. Implement footer with Refresh/Cancel buttons
4. Handle performance warning states

### Phase 3: Migration
1. Update `/grid/[id]/table.tsx` to use `QueryDataGrid`
2. Update `/q/[id]/table.tsx` to use `QueryDataGrid`
3. Update `/item/[id]` if applicable
4. Remove duplicated logic from `GridSession`, `QueryData`

### Phase 4: Cleanup
1. Remove old `DataFetchContext` (merged into `DataContext`)
2. Simplify `GridSession` to only handle chat/UI state
3. Remove `fetchEnabled` remnants if any

## File Structure

```
app/
├── contexts/
│   ├── DataContext/
│   │   ├── index.tsx        # Provider + hook
│   │   ├── types.ts         # QueryState, etc.
│   │   └── useQueryState.ts # Helper hooks
│   └── GridSession/         # Chat/UI state only
├── components/
│   └── QueryDataGrid/
│       ├── index.tsx        # Main component
│       ├── overlays.tsx     # Fetch/Error/Loading overlays
│       └── footer.tsx       # Refresh/Cancel buttons
```

## Dashboard Items Behavior

Dashboard items (charts/tables on home page) have different behavior than full grid view.

### Fetch Strategy

| State | Dashboard Item | Grid View |
|-------|----------------|-----------|
| Has cache | Show cached data | Show cached data |
| No cache, no warning | Auto-fetch → spinner → data | Show Fetch button |
| No cache, has warning | Show refresh IconButton (centered) | Show Fetch & Notify button |
| Fetching | Spinner overlay | Spinner + Cancel |
| Error | Error + retry icon | Error + Retry button |

### Rationale

- **Auto-fetch for no-warning queries**: Dashboard items are typically smaller, frequently accessed, and should load quickly
- **Explicit fetch for warning queries**: Expensive queries shouldn't auto-fire on dashboard load, preventing accidental expensive operations
- **Minimal UI**: Dashboard items use IconButton (circular arrow) instead of full buttons to save space

### IconButton Behavior

- **Icon**: Circular refresh/arrow icon
- **Position**: Centered overlay on the dashboard item
- **Tooltip**: "This query may take a while. Click to fetch."
- **Optional**: Show estimated row count from metadata if available

### Reference: Superset Approach

Apache Superset uses similar auto-fetch with cache-first strategy:
- Fetch on component mount
- Server-side Redis cache (1-day default TTL)
- Concurrent requests for all visible charts
- Cache warm-up via background jobs (Airflow)

Our approach adds client-side localStorage cache and explicit fetch for expensive queries.

## Data API Design

### Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/data/sse/{query_id}` | SSE stream for data fetch |
| DELETE | `/data/{query_id}` | Cancel/unsubscribe from fetch |
| PATCH | `/data/{query_id}` | Update subscription (add/remove notification) |

### GET `/data/sse/{query_id}`

Existing SSE endpoint with additional params:

| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Page size (default 100) |
| `offset` | int | Pagination offset |
| `sort_by` | string | Sort column |
| `sort_order` | asc/desc | Sort direction |
| `force` | boolean | Force refresh, bypass local cache |
| `notify` | boolean | Send email notification on complete |
| `user_email` | string | Email for notification |

### DELETE `/data/{query_id}`

Cancel/unsubscribe from running fetch.

**Behavior:**
- If user is the **only subscriber** → cancel the Celery task entirely
- If **other users are subscribed** → just unsubscribe this user (task continues)

**Request:** No body required (user identified from auth)

**Response:**
```json
{
  "status": "cancelled" | "unsubscribed",
  "message": "Fetch cancelled" | "Unsubscribed from shared fetch"
}
```

### PATCH `/data/{query_id}`

Update subscription settings for running fetch.

**Request:**
```json
{
  "notify": true | false,
  "user_email": "user@example.com"  // required if notify=true
}
```

**Response:**
```json
{
  "status": "updated",
  "notify": true,
  "user_email": "user@example.com"
}
```

### Cache Invalidation Strategy

| Action | Local Cache (localStorage) | Server Cache (Redis) |
|--------|---------------------------|---------------------|
| `force=true` | Invalidate | Keep (shared by users) |
| Normal fetch | Check first | Check first |
| TTL expiry | Auto-invalidate | Auto-invalidate |

**Rationale:** Force refresh only invalidates local cache. Server-side Redis cache is shared across users, so one user's force refresh shouldn't invalidate cache for others.

### SSE Events

| Event | Payload | Description |
|-------|---------|-------------|
| `connected` | `{session_id}` | Connection established |
| `reconnected` | `{message}` | Reconnected to running query |
| `count` | `{total_rows}` | Row count available |
| `data` | `{rows, total_rows}` | Data payload |
| `error` | `{error}` | Fetch error |
| `cancelled` | `{message}` | Fetch was cancelled |
| `workers_busy` | `{message}` | Workers busy, waiting |

## QueryDataGrid Integration Plan (Monolithic Webapp)

### Target Pages

| Page | Current State | Complexity |
|------|--------------|------------|
| `/q/[id]` | Uses `QueryDataProvider` + manual infinite scroll | Low |
| `/grid/[session_id]` | Uses `GridSessionProvider` + manual infinite scroll | Medium |
| Dashboard | **Does not exist yet** | New implementation |

### 1. `/q/[id]` Query Page (Simplest)

**Current architecture:**
- `QueryDataProvider` wraps page with custom context
- `QueryContainer` has manual infinite scroll event listener
- `DataTable` renders `DataGridPro` with custom overlays

**Migration:**
```typescript
// Before: 3 layers of components + custom context
<QueryDataProvider>
  <QueryContainer>  // Manual scroll listener
    <DataTable />   // DataGridPro wrapper
  </QueryContainer>
</QueryDataProvider>

// After: Single component, state in parent
<QueryContainer>
  <QueryDataGrid
    queryId={id}
    columns={gridColumns}
    queryMetadata={query}
    paginate={true}
    performanceWarning={query?.performance_warning}
    ...
  />
</QueryContainer>
```

**Files to delete:** `table.tsx`, custom overlay components
**Files to simplify:** `query-container.tsx` (remove scroll listener)

### 2. `/grid/[session_id]` Grid Page (Medium)

**Current architecture:**
- `GridSessionProvider` manages session + data + chat
- `InteractiveDashboard` has resizable split pane + manual scroll
- `DataTable` similar to `/q/[id]`
- Multi-view tabs: Grid, Charts, SQL

**Migration:**
```typescript
// Keep: Split pane, chat, tabs, charts
// Replace: DataTable with QueryDataGrid

<InteractiveDashboard>
  <LeftPane>
    <ChatContainer />
  </LeftPane>
  <Divider />
  <RightPane>
    <Tabs>
      <TabPanel index={0}>
        <QueryDataGrid ... />  // Replaces DataTable
      </TabPanel>
      <TabPanel index={1}>
        <ChartView rows={rows} />  // Uses same data
      </TabPanel>
      <TabPanel index={2}>
        <HighlightedSQL />
      </TabPanel>
    </Tabs>
  </RightPane>
</InteractiveDashboard>
```

**Keep:** `GridSessionProvider` for session-specific state (chat, sections)
**Delete:** `table.tsx`, `data-grid-overlays.tsx`
**Modify:** `interactive-dashboard.tsx` (remove scroll listener)

### 3. Dashboard Widgets (New)

**Proposed structure:**
```typescript
// New: /app/dashboard/page.tsx
<DashboardPage>
  <Grid container>
    {widgets.map((widget) => (
      <Grid item xs={12} md={6} lg={4}>
        <Paper>
          <Typography>{widget.title}</Typography>
          <QueryDataGrid
            queryId={widget.queryId}
            columns={widget.columns}
            paginate={false}  // Fetch all for widgets
            pageSize={50}
            ...
          />
        </Paper>
      </Grid>
    ))}
  </Grid>
</DashboardPage>
```

Each widget is an independent `QueryDataGrid` instance with its own state.

### Key Differences: Current vs QueryDataGrid

| Feature | Current | QueryDataGrid |
|---------|---------|---------------|
| Infinite scroll | Manual event listener | Built-in |
| Overlays | Custom per-page | 5 standardized |
| CSV export | None | Built-in |
| Notifications | Manual state | Props-based |
| Cache | SWR `app-cache` | DataContext (with legacy fallback) |
| Row ID | `id: index` | `_gridId: row.id ?? index` |

### Migration Order

1. **`/q/[id]`** - Lowest risk, establishes pattern
2. **`/grid/[session_id]`** - Slightly more complex, has split pane
3. **Dashboard** - New implementation using established pattern

## Related Docs
- `docs/future/data-freshness-strategy.md` - TTL and max_age strategy
