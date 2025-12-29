# QueryDataGrid Migration Plan

## Overview

This document outlines the migration plan for replacing custom DataTable implementations with the unified `QueryDataGrid` component across two routes:
- `/q/[id]` - Standalone query view
- `/grid/[id]` - Interactive session view

## Current Architecture

### Route 1: `/q/[id]` - Standalone Query View

**Component Hierarchy:**
```
QueryPage (server component)
  └── QueryDataProvider (context)
      └── QueryContainer
          └── DataTable
              └── DataGridPro
```

**Characteristics:**
- Manual fetch trigger (user clicks "Fetch" button)
- Uses `QueryDataProvider` for state management
- Custom DataTable: ~280 lines
- Custom overlays for fetch/loading/error states

### Route 2: `/grid/[id]` - Interactive Session View

**Component Hierarchy:**
```
InteractiveQueryPage (server component)
  └── GridSessionProvider (context)
      └── InteractiveDashboard
          ├── ChatContainer
          └── DataTable
              └── DataGridPro
```

**Characteristics:**
- Auto fetch when query available
- Uses `GridSessionProvider` (superset of QueryData + chat/prompt/sections)
- Custom DataTable: ~300 lines + ~100 lines overlays
- Selection state flows UP to chat for AI context

## State Management Comparison

### QueryDataProvider (`/q/[id]`)
```typescript
{
  rows: any[];
  rowCount: number;
  gridColumns: GridColDef[];
  activeColumn: GridColDef | null;
  activeRows: any[] | undefined;
  selectionModel: number[];
  paginationModel: { page, pageSize };
  sortModel: GridSortItem[];
  isLoading: boolean;
  isValidating: boolean;
  isReachingEnd: boolean;
  error: any;
  hasCachedData: boolean;
  onFetchData: (withNotification?: boolean) => void;
  setSize: (pages) => void;
}
```

### GridSessionProvider (`/grid/[id]`)
Includes all of QueryDataProvider PLUS:
```typescript
{
  sections: TChatSection[];     // Chat history
  promptVal: string;            // Current prompt input
  pending: boolean;             // Is request pending?
  metadata: any;                // Session-level metadata
  query: any;                   // Current query object
  requestId: string | undefined;
  selectedAction: string;
  context: string;              // Selected context for action
  scrollRef: RefObject<HTMLDivElement>;
  scrollToBottom: () => void;
}
```

## New Components

### DataContext (`apps/web/app/contexts/DataContext`)
Global data fetching context that manages:
- SSE connections for streaming data
- Local cache (localStorage + in-memory)
- Fetch state per query (pending, success, error)
- Force refresh and cache invalidation

### QueryDataGrid (`apps/web/app/components/QueryDataGrid`)
Unified DataGrid component with:
- Built-in overlays (7 UI states)
- Server-side sorting and pagination
- Infinite scroll support
- Column descriptions from metadata
- Selection state (column/row highlighting)
- NEW COLUMN button support
- Refs callback for AI context exposure

**Props Interface:**
```typescript
interface QueryDataGridProps {
  queryId: string;
  columns: GridColDef[];
  queryMetadata?: TQuery | null;
  useSSE?: boolean;
  paginate?: boolean;
  performanceWarning?: boolean;
  estimatedRows?: number;
  estimatedSizeGb?: number;
  sortModel?: GridSortItem[];
  onSortModelChange?: (model: GridSortItem[]) => void;
  activeColumn?: GridColDef | null;
  onActiveColumnChange?: (column: GridColDef | null) => void;
  activeRows?: any[];
  onActiveRowsChange?: (rows: any[] | undefined) => void;
  selectionModel?: number[];
  onSelectionModelChange?: (selection: number[]) => void;
  pageSize?: number;
  showAddColumn?: boolean;
  onAddColumn?: () => void;
  onRefsChange?: (refs: DataGridRefs) => void;
}

interface DataGridRefs {
  cols?: (string | undefined)[];  // [column_name, ...values]
  rows?: (string | any[])[];      // [headers, ...row_values]
}
```

## Migration Strategy

### Phase 1: `/q/[id]` Migration (Simpler)

**Files to Modify:**

1. `apps/web/app/q/[id]/page.tsx`
   - Wrap with DataProvider (or add to layout)

2. `apps/web/app/q/[id]/table.tsx`
   - Replace custom DataTable with QueryDataGrid
   - Remove overlay logic
   - Remove sort/pagination handlers

3. `apps/web/app/q/[id]/query-container.tsx`
   - Remove infinite scroll listener (now in QueryDataGrid)
   - Keep tabs/layout

**Before (table.tsx):**
```typescript
export const DataTable = () => {
  const { rows, gridColumns, activeColumn, ... } = useQueryData();
  // 280 lines of custom logic
  return <DataGridPro ... />;
};
```

**After (table.tsx):**
```typescript
export const DataTable = () => {
  const { activeColumn, setActiveColumn, ... } = useQueryData();
  const { data: queryMetadata } = useQueryObject(queryId);
  
  return (
    <QueryDataGrid
      queryId={queryId}
      columns={gridColumns}
      queryMetadata={queryMetadata}
      activeColumn={activeColumn}
      onActiveColumnChange={setActiveColumn}
      activeRows={activeRows}
      onActiveRowsChange={setActiveRows}
      performanceWarning={queryMetadata?.explanation?.performance_warning}
    />
  );
};
```

**Estimated Reduction:** 390 lines → 160 lines (59%)

### Phase 2: `/grid/[id]` Migration (Complex)

**Key Challenge:** Selection state flows UP to chat for AI context.

**Solution:** Use `onRefsChange` callback to expose selection data.

**Files to Modify:**

1. `apps/web/app/grid/[id]/table.tsx`
   - Replace custom DataTable with QueryDataGrid
   - Add `showAddColumn` and `onAddColumn` props

2. `apps/web/app/grid/[id]/data-grid-overlays.tsx`
   - Remove (overlays now in QueryDataGrid)

3. `apps/web/app/grid/[id]/interactive-dashboard.tsx`
   - Consume refs from QueryDataGrid for AI context
   - Keep chat and chart logic

**Before:**
```typescript
// interactive-dashboard.tsx
const { activeColumn, activeRows } = useGridSession();
// Build AI context manually from selection state
```

**After:**
```typescript
// interactive-dashboard.tsx
const [refs, setRefs] = useState<DataGridRefs>({});

<QueryDataGrid
  queryId={query?.query_id}
  onRefsChange={setRefs}
  showAddColumn={true}
  onAddColumn={() => setNewCol(true)}
  ...
/>

// Use refs.cols and refs.rows for AI context
```

**Estimated Reduction:** 400 lines → 100 lines (75%)

### Phase 3: Cleanup

**Remove/Deprecate:**
- Old `DataFetchContext` (merged into DataContext)
- Duplicate overlay components in both routes
- Redundant state management code

**Simplify:**
- `QueryDataProvider` becomes thin wrapper (selection state only)
- `GridSessionProvider` focuses on chat/UI state

## Data Flow Changes

### Current Flow
```
User action → Context provider → useInfiniteQuery (SWR) → DataTable renders
```

### New Flow
```
User action → DataContext.fetchQuery() → SSE/fetch → QueryDataGrid subscribes → Renders
                                                   ↓
                                            onRefsChange callback
                                                   ↓
                                            Parent gets structured data for AI
```

## Key Insights

1. **Duplication:** Both routes have ~95% identical DataTable logic

2. **Refs Pattern:** The `onRefsChange` callback allows parent components to receive structured selection data without managing DataGrid internals

3. **Performance Warning:** Currently handled differently in each route; QueryDataGrid normalizes via props

4. **New Column Button:** Only needed in `/grid/[id]`; supported via optional props

## Testing Checklist

- [ ] `/q/[id]` displays data correctly
- [ ] `/q/[id]` fetch/force/cancel buttons work
- [ ] `/q/[id]` infinite scroll loads more data
- [ ] `/q/[id]` column/row selection highlights correctly
- [ ] `/q/[id]` sort triggers server-side sort
- [ ] `/grid/[id]` auto-fetches when query available
- [ ] `/grid/[id]` selection state available for AI context
- [ ] `/grid/[id]` NEW COLUMN button works
- [ ] `/grid/[id]` chat actions use refs data
- [ ] Cache persists across page reloads
- [ ] SSE cancellation works correctly

## Files Reference

**New Components:**
- `apps/web/app/contexts/DataContext/index.tsx`
- `apps/web/app/contexts/DataContext/types.ts`
- `apps/web/app/components/QueryDataGrid/index.tsx`
- `apps/web/app/components/QueryDataGrid/types.ts`
- `apps/web/app/components/QueryDataGrid/footer.tsx`
- `apps/web/app/components/QueryDataGrid/overlays.tsx`

**Test Page:**
- `apps/web/app/data-test/[id]/page.tsx`

**To Migrate:**
- `apps/web/app/q/[id]/table.tsx`
- `apps/web/app/q/[id]/query-container.tsx`
- `apps/web/app/grid/[id]/table.tsx`
- `apps/web/app/grid/[id]/data-grid-overlays.tsx`
- `apps/web/app/grid/[id]/interactive-dashboard.tsx`
