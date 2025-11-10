# V2 Migration Strategy

**Date**: 2025-11-09  
**Status**: Architecture proposal

## Problem Statement

We need to introduce v2 architecture (message-based, hybrid SSE) while:
1. **Not touching legacy pages** (`/chat`, `/query`, `/grid`) - they continue working
2. **Keeping dashboards working** - they're read-only, display static queries
3. **Clear separation** at API, context, and hook layers
4. **Smooth transition** for users

## Key Insight: Dashboards Don't Need v2

**Current dashboard flow**:
```
Dashboard → getDashboardItemData() → getQuery(queryId) → GET /api/v1/query/{id}
    ↓
Static query metadata + data
    ↓
Render table/chart (read-only)
```

**Why this is fine**:
- Dashboards are **read-only** (no chat, no refinement)
- They use immutable queries (via `query_id`)
- No agentic flows, no sessions
- Just fetch data and render

**Conclusion**: Dashboards can stay on v1 API indefinitely. They're orthogonal to the chat/query interface.

---

## Proposed Architecture

### Directory Structure

```
apps/web/app/
├── (legacy routes - untouched)
│   ├── chat/[id]/              # V1 - keep as-is
│   ├── query/[id]/             # V1.5 - keep as-is  
│   ├── grid/[id]/              # V1.5 - keep as-is
│   └── q/[id]/                 # Query-only - keep as-is
│
├── (dashboards - v1 forever)
│   ├── (dash)/[[...section]]/  # Uses v1 API (getQuery)
│   └── item/[id]/              # Dashboard item detail
│
├── (new v2 routes)
│   └── nb/                     # "Notebook" - V2 interface
│       └── [id]/
│           └── page.tsx        # V2 notebook interface
│
├── lib/
│   ├── gptAPI.ts               # V1 API client (legacy, dashboards)
│   └── v2/
│       └── api.ts              # V2 API client (new routes only)
│
├── contexts/
│   ├── (legacy contexts - keep)
│   │   ├── App/
│   │   ├── ChatSession/
│   │   └── GridSession/
│   │
│   └── v2/                     # V2 contexts (isolated)
│       ├── SessionProvider.tsx
│       └── MessageSession.tsx
│
├── components/
│   ├── (shared - version agnostic)
│   │   ├── data-grid/
│   │   ├── navigation/
│   │   └── dashboard/
│   │
│   ├── (legacy - v1 specific)
│   │   └── chat/
│   │
│   └── v2/                     # V2 components
│       ├── cells/
│       └── progress/
│
└── hooks/
    ├── (legacy hooks)
    │   ├── useUserSession.ts
    │   └── useUserSessions.ts
    │
    └── v2/                     # V2 hooks
        ├── useV2Session.ts
        └── useMessages.ts
```

### Key Principles

**1. Isolation by Directory**
- V2 code lives in `v2/` subdirectories
- No cross-contamination (v1 never imports from v2/, v2 never imports from legacy)
- Shared components (data-grid, charts) are version-agnostic

**2. No Environment Switches**
- Routes determine which version to use
- `/query/[id]` → Always v1 API + contexts
- `/nb/[id]` → Always v2 API + contexts
- Dashboards → Always v1 API (read-only queries)

**3. Backend API Separation**
- V1 client: `lib/gptAPI.ts` → `/api/v1/*`
- V2 client: `lib/v2/api.ts` → `/api/v2/*`
- No shared state, no version conditionals

**4. User-Driven Migration**
- Default: Users land on legacy routes
- Banner: "Try the notebook interface (beta)" → link to `/nb/[id]`
- Parallel running until v2 is stable
- Eventually redirect `/query/*` → `/nb/*`

---

## Detailed Design

### 1. V2 Route: `/nb/[id]`

**Why `/nb/`?**
- Short (2 chars), memorable
- Alludes to "notebook" (Jupyter-inspired UX)
- Clearly distinct from `/query`, `/grid`, `/chat`
- Future-proof (can add `/nb/new`, `/nb/shared/[id]`, etc.)

**Page Structure**:
```typescript
// app/nb/[id]/page.tsx
import { V2SessionProvider } from '@/app/contexts/v2/SessionProvider';
import { MessageSessionProvider } from '@/app/contexts/v2/MessageSession';
import { NotebookInterface } from '@/app/components/v2/NotebookInterface';

export default function NotebookPage({ params }: { params: { id: string } }) {
  return (
    <V2SessionProvider sessionId={params.id}>
      <MessageSessionProvider sessionId={params.id}>
        <NotebookInterface />
      </MessageSessionProvider>
    </V2SessionProvider>
  );
}
```

**Layout**: Minimal layout (no v1 navigation baggage)

---

### 2. API Layer Separation

**V1 Client** (`lib/gptAPI.ts`):
```typescript
// Existing v1 client - DO NOT MODIFY
// Used by: /chat, /query, /grid, /q, dashboards

export const createUserSession = ...
export const createUserRequest = ...
export const getQuery = ...  // Used by dashboards
// etc.
```

**V2 Client** (`lib/v2/api.ts`):
```typescript
// New v2 client
// Used by: /sg routes ONLY

import createClient from 'openapi-fetch';
import type { paths } from '@/app/api/v2/types.gen';

const client = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL,
});

export async function createV2Session(req: CreateSessionRequest, token: string) {
  const { data, error } = await client.POST('/api/v2/sessions', {
    headers: { Authorization: `Bearer ${token}` },
    body: req,
  });
  if (error) throw new Error(error.detail);
  return data;
}

export async function sendMessage(
  sessionId: string,
  message: SendMessageRequest,
  token: string
) {
  const { data, error } = await client.POST('/api/v2/sessions/{session_id}/messages', {
    headers: { Authorization: `Bearer ${token}` },
    params: { path: { session_id: sessionId } },
    body: message,
  });
  if (error) throw new Error(error.detail);
  return data;
}

export async function getMessages(
  sessionId: string,
  options: GetMessagesOptions,
  token: string
) {
  const { data, error } = await client.GET('/api/v2/sessions/{session_id}/messages', {
    headers: { Authorization: `Bearer ${token}` },
    params: { 
      path: { session_id: sessionId },
      query: options
    },
  });
  if (error) throw new Error(error.detail);
  return data;
}

// ... other v2 functions
```

**Type Generation**:
```bash
# Generate v2 types from backend OpenAPI spec
cd apps/web
npm run generate:v2  # New script, points to /api/v2/openapi.json
```

**Result**: Two completely separate API clients, no conditionals, no version checking.

---

### 3. Context Separation

**V1 Contexts** (existing, untouched):
```
contexts/
├── App/                    # Global app state (used everywhere)
├── ChatSession/            # V1 query interface
├── GridSession/            # V1 grid interface
├── SessionStatus/          # V1 SSE
├── QueryData/              # Read-only queries
└── Tutorial/               # Tutorial mode
```

**V2 Contexts** (new, isolated):
```
contexts/v2/
├── SessionProvider.tsx     # V2 SSE connection manager
├── MessageSession.tsx      # V2 message state
└── NotebookUI.tsx          # V2 notebook UI state (optional)
```

**Key**: V2 contexts live in `contexts/v2/`, never imported by v1 routes.

---

### 4. Component Sharing Strategy

**Shared Components** (version-agnostic):
```
components/
├── data-grid/
│   ├── DataTable.tsx           # Works with any data
│   └── StyledValue.tsx          # Cell formatter
├── charts/
│   ├── BarChart.tsx
│   ├── LineChart.tsx
│   └── PieChart.tsx
├── sql/
│   └── SqlView.tsx              # Syntax highlighting
└── navigation/
    ├── TopNavClient.tsx
    └── UserProfileMenu.tsx
```

These components are "dumb" - they receive props, render UI, no version-specific logic.

**V1-Specific Components**:
```
components/chat/              # Chat bubbles (v1 style)
components/query/             # V1 query interface
```

**V2-Specific Components**:
```
components/v2/
├── cells/
│   ├── MessageCell.tsx       # Notebook cell
│   ├── UserInputCell.tsx
│   ├── AssistantCell.tsx
│   └── NoteCell.tsx
├── progress/
│   └── AgentProgress.tsx     # Real-time progress
└── notebook/
    └── NotebookInterface.tsx # Main v2 interface
```

**Pattern**: Shared components take data as props, don't care about sessions/messages/requests.

Example:
```typescript
// Shared component (version-agnostic)
export function DataTable({ columns, data, onSortChange, ... }) {
  return <MuiDataGrid ... />;
}

// V1 usage
function ChatSessionInterface() {
  const { queryData } = useChatSession();
  return <DataTable columns={queryData.columns} data={queryData.data} />;
}

// V2 usage
function NotebookInterface() {
  const { messages } = useMessageSession();
  const tableMessage = messages.find(m => m.kind === 'table');
  return <DataTable columns={tableMessage.metadata.columns} data={tableMessage.content} />;
}
```

---

### 5. Hook Separation

**V1 Hooks** (existing):
```
hooks/
├── useUserSession.ts          # Fetch v1 session
├── useUserSessions.ts         # List v1 sessions
└── useInfiniteQuery.ts        # Pagination (shared)
```

**V2 Hooks** (new):
```
hooks/v2/
├── useV2Session.ts            # Hook into V2SessionProvider
├── useMessages.ts             # Hook into MessageSessionProvider
└── useAgentStatus.ts          # Current agent step
```

Example:
```typescript
// hooks/v2/useMessages.ts
import { useMessageSession } from '@/app/contexts/v2/MessageSession';

export function useMessages() {
  const { messages, sendMessage, loading, error } = useMessageSession();
  
  return {
    messages,
    sendMessage,
    loading,
    error,
    // Convenience methods
    userMessages: messages.filter(m => m.role === 'user'),
    assistantMessages: messages.filter(m => m.role === 'assistant'),
    latestMessage: messages[messages.length - 1],
  };
}
```

---

### 6. Dashboard Compatibility

**No Changes Needed**:
```
(dash)/[[...section]]/page.tsx
    ↓
getDashboardItemData(id)
    ↓
getQuery(queryId)  ← V1 API (lib/gptAPI.ts)
    ↓
GET /api/v1/query/{id}
    ↓
Render static data
```

Dashboards continue using v1 API because:
- They're read-only
- No sessions, no chat, no refinement
- Query data is immutable
- v1 `/api/v1/query/{id}` endpoint won't go away (it's just fetching static data)

**Future Enhancement** (optional):
If we want dashboard items to link to v2 interface:
```typescript
// item/[id]/page.tsx
const item = await getDashboardItemData(id);

// Link to v2 instead of v1
const href = `/nb/new?queryId=${item.query.queryUid}`;  // Opens in v2 interface
```

---

## User Experience Flow

### Initial State (Today)

```
User lands on app
    ↓
Default route: /query/[id] (v1.5)
    ↓
Uses v1 API + polling
```

### With V2 Available

```
User lands on app
    ↓
Default: /query/[id] (v1.5)
    ↓
Banner: "Try notebook interface (beta)" [Try It]
    ↓
Clicks banner → Redirect to /nb/[new-session-id]
    ↓
V2 notebook interface with cells + real-time SSE
```

### User Navigation

**Legacy Routes**:
- `/query/[id]` - V1.5 (polling, chat bubbles)
- `/grid/[id]` - V1.5 grid (basic SSE)
- `/chat/[id]` - V1 legacy

**New Route**:
- `/nb/[id]` - V2 (hybrid SSE, notebook cells)

**Dashboards** (unchanged):
- `/` - Home dashboard
- `/tokens` - Token dashboard
- `/trends` - Trends dashboard
- Click item → `/item/[id]` (view static query)

**Migration Path**:
- "Try V2" button in v1 interface
- Creates new v2 session, redirects to `/nb/[id]`
- User can switch back and forth
- Eventually: Redirect `/query/*` → `/nb/*` (after v2 is stable)

---

## Implementation Checklist

### Phase 1: Foundation

- [ ] Create `lib/v2/` directory
- [ ] Implement v2 API client (`lib/v2/api.ts`)
- [ ] Generate v2 types (`npm run generate:v2`)
- [ ] Create `contexts/v2/` directory
- [ ] Implement `V2SessionProvider` (SSE)
- [ ] Implement `MessageSessionProvider` (state)
- [ ] Create `components/v2/` directory
- [ ] Build basic `NotebookInterface` component
- [ ] Create `/nb/[id]/` route
- [ ] Test end-to-end (create session, send message, receive events)

### Phase 2: Components

- [ ] Build `MessageCell` component (base)
- [ ] Build `UserInputCell`, `AssistantCell`, `NoteCell`
- [ ] Build `AgentProgress` component
- [ ] Build execution order badge component
- [ ] Integrate shared components (DataTable, SqlView, Charts)
- [ ] Build collapsible output areas
- [ ] Build cell action menus (re-run, fold, edit, delete)

### Phase 3: Features

- [ ] Message editing
- [ ] Message re-execution
- [ ] Markdown note cells
- [ ] Keyboard shortcuts
- [ ] Control endpoints (cancel, interrupt)
- [ ] Export to notebook (optional)

### Phase 4: Polish

- [ ] Error handling
- [ ] Loading states
- [ ] Empty states
- [ ] Mobile responsiveness
- [ ] Accessibility
- [ ] Performance optimization

### Phase 5: User Migration

- [ ] Add "Try V2" banner to v1 routes
- [ ] Analytics (track v2 usage)
- [ ] Feedback mechanism
- [ ] Bug fixes based on feedback
- [ ] Gradual rollout (feature flag)
- [ ] Redirect v1 → v2 (when ready)
- [ ] Deprecate v1 routes (eventually)

---

## Directory Tree (Complete)

```
apps/web/app/
│
├── (legacy - untouched)
│   ├── chat/[id]/
│   │   ├── page.tsx                # V1 chat (keep)
│   │   └── layout.tsx
│   ├── query/[id]/
│   │   ├── page.tsx                # V1.5 query (keep)
│   │   └── layout.tsx
│   ├── grid/[id]/
│   │   ├── page.tsx                # V1.5 grid (keep)
│   │   └── layout.tsx
│   └── q/[id]/
│       └── page.tsx                # Query-only (keep)
│
├── (dashboards - v1 forever)
│   ├── (dash)/[[...section]]/
│   │   └── page.tsx                # Uses v1 getQuery
│   └── item/[id]/
│       └── page.tsx                # Dashboard item
│
├── (v2 - new)
│   └── nb/[id]/
│       ├── page.tsx                # V2 notebook interface
│       └── layout.tsx              # Minimal layout
│
├── lib/
│   ├── gptAPI.ts                   # V1 client (legacy, dashboards)
│   ├── types.ts                    # V1 types
│   └── v2/
│       ├── api.ts                  # V2 client (new)
│       └── types.ts                # V2 types (generated)
│
├── contexts/
│   ├── App/                        # Global (shared)
│   ├── Theme/                      # Global (shared)
│   ├── (v1 contexts - keep)
│   │   ├── ChatSession/
│   │   ├── GridSession/
│   │   ├── SessionStatus/
│   │   └── QueryData/
│   └── v2/
│       ├── SessionProvider.tsx    # V2 SSE
│       └── MessageSession.tsx     # V2 state
│
├── components/
│   ├── (shared - version agnostic)
│   │   ├── data-grid/
│   │   │   ├── DataTable.tsx
│   │   │   └── StyledValue.tsx
│   │   ├── charts/
│   │   │   ├── BarChart.tsx
│   │   │   ├── LineChart.tsx
│   │   │   └── PieChart.tsx
│   │   ├── sql/
│   │   │   └── SqlView.tsx
│   │   ├── navigation/
│   │   │   ├── TopNavClient.tsx
│   │   │   └── UserProfileMenu.tsx
│   │   └── dashboard/
│   │       ├── DashboardGrid.tsx
│   │       ├── DashboardItem.tsx
│   │       └── DashboardItemPage.tsx
│   │
│   ├── (v1 specific - keep)
│   │   ├── chat/
│   │   └── query/
│   │
│   └── v2/
│       ├── cells/
│       │   ├── MessageCell.tsx
│       │   ├── UserInputCell.tsx
│       │   ├── AssistantCell.tsx
│       │   └── NoteCell.tsx
│       ├── progress/
│       │   └── AgentProgress.tsx
│       └── notebook/
│           └── NotebookInterface.tsx
│
├── hooks/
│   ├── (shared)
│   │   ├── useLocalStorage.ts
│   │   └── useInfiniteQuery.ts
│   ├── (v1 hooks - keep)
│   │   ├── useUserSession.ts
│   │   └── useUserSessions.ts
│   └── v2/
│       ├── useV2Session.ts
│       ├── useMessages.ts
│       └── useAgentStatus.ts
│
└── api/
    ├── apegpt/                    # V1 proxies (keep)
    │   ├── sessions/
    │   ├── message/
    │   └── sse/
    └── v2/                        # V2 proxies (new)
        ├── sessions/
        ├── messages/
        └── stream/
```

---

## Benefits of This Approach

### 1. **Zero Risk to Legacy**
- V1 routes completely untouched
- No regressions possible
- Dashboards keep working

### 2. **Clear Separation**
- V1 code in root directories
- V2 code in `v2/` subdirectories
- Easy to understand what's what
- Easy to delete v1 code later

### 3. **No Environment Variables**
- Route determines version
- No `if (useV2) { ... }` conditionals
- Simpler logic, fewer bugs

### 4. **Gradual Migration**
- Run v1 and v2 in parallel
- Users choose when to switch
- Rollback is just hiding the banner
- No forced migration

### 5. **Dashboard Compatibility**
- Dashboards use v1 API forever (it's just static queries)
- No breaking changes
- No migration needed

### 6. **Future-Proof**
- `/nb/` namespace can grow
- Can add `/nb/new`, `/nb/shared/[id]` later
- V1 deprecation is just removing old routes
- Clean slate for v2

---

## Alternative Considered: Environment Switch

**Rejected Approach**:
```typescript
const API_VERSION = process.env.NEXT_PUBLIC_API_VERSION || 'v1';

function useSession() {
  if (API_VERSION === 'v2') {
    return useV2Session();
  } else {
    return useV1Session();
  }
}
```

**Why Rejected**:
- ❌ Conditional logic everywhere
- ❌ Hard to test both versions
- ❌ Accidental cross-contamination
- ❌ Can't run v1 and v2 simultaneously
- ❌ Deployment complexity (separate builds)
- ❌ No gradual migration path

---

## Recommendation

**Proceed with route-based separation**:
- New route: `/nb/[id]` for v2 (notebook interface)
- Isolated directories: `lib/v2/`, `contexts/v2/`, `components/v2/`
- No environment switches
- Dashboards stay on v1 API (they're read-only, no migration needed)
- Parallel running until v2 is stable
- Eventually redirect `/query` → `/nb`

This gives us:
- Clean separation
- Zero risk to legacy
- Gradual migration
- Easy rollback
- Dashboard compatibility
- Future-proof architecture

---

**Last Updated**: 2025-11-09
