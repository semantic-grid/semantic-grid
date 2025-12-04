# Grid as Embeddable Service

## Vision

Transform the query grid into a standalone, embeddable data visualization service that can be used by any agentic chat interface (Claude, ChatGPT, custom agents) via MCP UI / MCP Apps.

```
┌──────────────────────────────────────────────────────────┐
│  ANY Agentic Chat (Claude, ChatGPT, custom, etc.)        │
│                                                          │
│  Agent: "Here's the data you requested"                  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  MCP UI Component / App                            │  │
│  │  grid.semantic-grid.com/q/{query_id}?sort=...      │  │
│  │                                                    │  │
│  │  [User selects rows 5, 12]                         │  │
│  │           │                                        │  │
│  └───────────┼────────────────────────────────────────┘  │
│              ▼                                           │
│  Agent receives: { refs: { rows: [...] } }               │
│  Agent: "I see you selected 2 wallets. Want me to..."    │
└──────────────────────────────────────────────────────────┘
```

## Key Differentiator

Similar to Sigma Computing embedded dashboards, but **agent-native**:

| Sigma | Semantic Grid |
|-------|---------------|
| Embeds whole workbooks | Embeds single query results (atomic/composable) |
| Passive displays for humans | Bidirectional - selection flows back to agent |
| BI tool | Agent-native data interface |
| - | MCP-compatible - any agent can render and interact |

## Architecture

### URL as API Contract

The grid becomes a stateless service where URL = complete state:

```
grid.semantic-grid.com/q/{query_id}
  ?view=table|chart
  &sort=column_name
  &dir=asc|desc
  &page=N
  &size=N
  &col=column_name        # highlighted column
  &rows=1,2,3             # highlighted rows
  &theme=light|dark
  &chrome=full|minimal|compact
  &chartType=bar|line|pie
  &x=column
  &y=column
```

### Two Operating Modes

**Standalone mode** (`/q/{query_id}` opened directly):
- URL **is** the state
- User selects row → URL updates → shareable link
- Browser back/forward works

**Embedded mode** (iframe in dashboard/chat):
- URL is just the **initial state**
- User selects row → `postMessage` to parent → URL doesn't change
- Parent decides what to do (store, broadcast, send to agent)

```typescript
const isEmbedded = window.parent !== window;

const handleSelectionChange = (rows) => {
  if (isEmbedded) {
    // Notify parent, don't touch URL
    window.parent.postMessage({
      type: 'SELECTION_CHANGED',
      payload: { rows, refs }
    }, '*');
  } else {
    // Standalone - update URL
    updateUrlParams({ rows: rows.join(',') });
  }
};
```

### Chrome Modes

```
?chrome=full      → All controls (standalone use)
?chrome=minimal   → No refresh/footer (embedded, parent controls)
?chrome=compact   → Minimal + denser rows, smaller fonts (dashboard tiles)
```

### Message Passing Protocol

```typescript
// Grid → Parent (selection changed)
window.parent.postMessage({
  type: 'SELECTION_CHANGED',
  payload: { 
    refs: { cols: ['wallet', '0x123...'], rows: [...] },
    queryId: 'abc123'
  }
}, '*');

// Grid → Parent (user requested action)
window.parent.postMessage({
  type: 'ACTION_REQUESTED',
  payload: { action: 'analyze', column: 'wallet' }
}, '*');

// Parent → Grid (update state)
iframe.contentWindow.postMessage({
  type: 'SET_STATE',
  payload: { sort: 'wallet', rows: [5, 12] }
}, 'https://grid.semantic-grid.com');

// Parent → Grid (provide data directly)
iframe.contentWindow.postMessage({
  type: 'DATA',
  payload: { rows: [...], columns: [...] }
}, 'https://grid.semantic-grid.com');
```

## MCP Integration

```typescript
// MCP Server exposes:
{
  "resources": [{
    "uri": "grid://semantic-grid/q/{query_id}",
    "mimeType": "application/x-semantic-grid",
    "render": {
      "url": "https://grid.semantic-grid.com/q/{query_id}",
      "params": ["sort", "dir", "page", "col", "rows", "view"]
    }
  }],
  
  "tools": [{
    "name": "show_query_results",
    "description": "Display query results in interactive grid",
    "inputSchema": {
      "queryId": "string",
      "sort": "string?",
      "highlight": "string[]?"
    },
    "returns": "grid://semantic-grid/q/{queryId}"
  }]
}
```

## Dashboard Integration

```
┌─────────────────────────────────────────────────────────────┐
│  Dashboard Shell (app.example.com/dashboard/dash_123)       │
│                                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ <iframe>            │  │ <iframe>            │          │
│  │ grid.../q/q_1       │  │ grid.../q/q_2       │          │
│  │ ?chrome=compact     │  │ ?view=chart         │          │
│  └─────────────────────┘  └─────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### Dashboard Item Storage

```typescript
interface DashboardItem {
  id: string;
  dashboardId: string;
  queryId: string;
  position: number;
  gridParams: {
    view: 'table' | 'chart';
    chrome: 'minimal' | 'compact';
    sort?: string;
    chartType?: 'bar' | 'line' | 'pie';
  };
}

// Render
const gridUrl = `${GRID_BASE}/q/${item.queryId}?${new URLSearchParams(item.gridParams)}`;
```

### Cross-Item Interactions

```typescript
// Dashboard shell listens to all iframes
window.addEventListener('message', (event) => {
  if (event.origin !== GRID_ORIGIN) return;
  
  const { type, queryId, payload } = event.data;
  
  if (type === 'SELECTION_CHANGED') {
    // Broadcast to linked items
    dashboardItems
      .filter(item => item.linkedTo === queryId)
      .forEach(item => {
        iframeRefs[item.id].postMessage({
          type: 'FILTER_BY',
          payload: { column: 'wallet', values: payload.selectedValues }
        });
      });
  }
});
```

## Views (Same Service)

Same data, different render - just swap the `view` param:

```
?view=table    → DataGrid
?view=chart    → Chart (bar, line, pie, scatter)
?view=pivot    → Pivot table (future)
?view=map      → Geo visualization (future)
?view=summary  → Aggregated stats (future)
```

```typescript
// /q/[id]/page.tsx
const view = searchParams.get('view') || 'table';
const { rows, columns } = useData();

if (view === 'chart') {
  return <QueryChart data={rows} columns={columns} {...chartParams} />;
}
return <QueryDataGrid data={rows} columns={columns} {...gridParams} />;
```

## Benefits

1. **True separation** - Grid is standalone product, chat apps are consumers
2. **Independent deployment** - Grid can be CDN-cached, versioned separately
3. **Embeddable anywhere** - Dashboards, docs, external tools, customer portals
4. **URL as API** - Clean contract, shareable links
5. **No bundle duplication concerns** - Different products, independent bundles
6. **Agent-native** - Any AI agent can render and interact via MCP

## Data Fetching & Caching

Each iframe has its own JS context (no SWR dedup across iframes). Options:

1. **Service Worker** - Intercept fetches at grid origin, dedup across iframes
2. **Parent as data broker** - Parent fetches, passes data via postMessage
3. **Backend cache** - Let iframes fetch independently, backend caches (simplest)

Recommendation: Start with backend caching. Add SW optimization later if needed.

```
iframe A fetch ──► API ──► Cache miss ──► DB ──► Cache set ──► Response
iframe B fetch ──► API ──► Cache hit ──────────────────────► Response
```

## Implementation Phases

### Phase 1: URL State (Foundation)
- Make `/q/[query_id]` fully URL-driven
- All state readable from / writable to URL params
- `useSearchParams` for state management

### Phase 2: Embed Mode
- Detect `window.parent !== window`
- Switch from URL updates to postMessage
- Add `chrome` param support

### Phase 3: Message Protocol
- Define and implement postMessage API
- Parent → Grid: SET_STATE, DATA, FILTER_BY
- Grid → Parent: SELECTION_CHANGED, ACTION_REQUESTED

### Phase 4: Dashboard Integration
- Update dashboard items to use iframe embeds
- Implement cross-item interactions
- Handle resize/layout

### Phase 5: MCP Integration
- Define MCP resource/tool schema
- Register with MCP server
- Test with various agents

## Related Docs

- [QueryDataGrid Migration Plan](./query-data-grid-migration.md)
- [DataContext Refactor](./data-context-refactor.md)
