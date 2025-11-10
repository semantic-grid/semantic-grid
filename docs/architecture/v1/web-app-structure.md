# Semantic Grid Web App Architecture

**Date**: 2025-11-09  
**Version**: Current state before v2 migration  
**Location**: `apps/web/`

## Executive Summary

The Semantic Grid web app is a Next.js 13+ application with multiple UX generations:
- **v1 (Legacy)**: `/chat/[id]` and older `/query/[id]` flows - Simple, DataOnly, Multistep backends
- **v1.5 (Current Primary)**: `/query/[id]` with InteractiveFlow - Rich chat + data grid
- **v1.5 Grid**: `/grid/[id]` - Chart-focused interface with SSE real-time updates  
- **Query-Only**: `/q/[id]` - Shareable, read-only queries
- **Dashboards**: `/(dash)/` - Curated collections from CMS

The backend has separate v1/v2 API modules ready, but frontend currently uses a `version` field to differentiate flows rather than URL-based routing.

---

## Table of Contents

1. [Route Structure](#1-route-structure)
2. [UX Evolution (v1 → v1.5 → v2)](#2-ux-evolution)
3. [API Integration](#3-api-integration)
4. [State Management](#4-state-management)
5. [Real-Time Updates (SSE)](#5-real-time-updates)
6. [Authentication](#6-authentication)
7. [Component Architecture](#7-component-architecture)
8. [Data Fetching Patterns](#8-data-fetching-patterns)
9. [Current Limitations & Pain Points](#9-current-limitations--pain-points)
10. [V2 Readiness Assessment](#10-v2-readiness-assessment)

---

## 1. Route Structure

### Primary User-Facing Routes

| Route | UX Version | Purpose | Key Features | Backend Flow |
|-------|-----------|---------|--------------|--------------|
| `/chat/[id]` | v1 (Legacy) | Chat-first interface | Basic chat, simple tables | Simple, DataOnly, Multistep |
| `/query/[id]` | **v1.5 (Primary)** | Interactive query refinement | Chat + tabs (Table/SQL/Chart), tutorial mode | **InteractiveFlow** |
| `/grid/[id]` | v1.5 Grid | Chart/visualization focus | SSE updates, chart types, column/row selection | InteractiveFlow |
| `/q/[id]` | Query-only | Shareable read-only queries | No agentic flows, immutable, OpenGraph | Direct query fetch |
| `/(dash)/[[...section]]` | Dashboard | Curated collections | Dynamic grid layout, CMS-driven | Multiple queries |

### Supporting Routes

- `/login` - Auth0 authentication
- `/admin/requests` - Admin request management
- `/item/[id]` - Dashboard item detail view

### Backend API Routes (Proxy Layer)

All located in `apps/web/app/api/`:

**`/api/apegpt/*`** - Flow Manager proxies
- `/api/apegpt/sessions` - Session CRUD
- `/api/apegpt/sessions/[id]` - Single session
- `/api/apegpt/message` - Get message by session + sequence
- `/api/apegpt/sse/[session_id]` - **SSE proxy** (real-time updates)
- `/api/apegpt/data/[id]` - Query data fetching
- `/api/apegpt/admin/requests` - Admin endpoint

**`/api/auth/*`** - Authentication
- `/api/auth/[auth0]` - Auth0 handlers
- `/api/auth/guest` - Guest token generation
- `/api/auth/session` - Session info

**`/api/dashboards/*`** - Dashboard management
**`/api/charts/*`** - Chart rendering
**`/api/ai/*`** - Client-side AI helpers

---

## 2. UX Evolution

### v1: Legacy Chat Interface (`/chat/[id]`)

**Timeline**: Early 2024  
**Backend Flows**: Simple, DataOnly, Multistep

**Architecture**:
- Page: `apps/web/app/chat/[id]/page.tsx`
- Layout: Full layout with AppBar, NavDrawer, ContextDrawer
- Components: `ChatContainer`, basic message rendering, simple tables
- Update Mechanism: **Polling** (no SSE)
- State: Basic `AppContext` only

**Features**:
- Text chat with bot responses
- Simple table rendering
- SQL view (syntax highlighted)
- Session management
- Model/DB/Flow selection in drawer

**Limitations**:
- No real-time updates
- Limited data grid features
- No chart support
- No query refinement UX
- Polling creates lag

**Status**: 🔴 **Legacy, minimal maintenance**

---

### v1.5: Interactive Query (`/query/[id]`) - PRIMARY INTERFACE

**Timeline**: Mid-2024  
**Backend Flow**: **InteractiveFlow** (backend API version 2)

**Architecture**:
- Page: `apps/web/app/query/[id]/page.tsx`
- Layout: Includes AppBar, tutorial overlay
- Contexts: `ChatSessionProvider`, `TutorialProvider`, `AppProvider`
- Components: `InteractiveDashboard`, `ChatContainer`, `DataTable` (MUI X DataGrid Pro)
- Update Mechanism: **Polling** with `pollForResponse` helper
- State: Rich context with active column/row selection, sorting, pagination

**Features**:
- ✅ Multi-tab interface (Table / SQL / Chart)
- ✅ Chat-based query refinement
- ✅ Rich data grid (MUI X DataGrid Pro)
  - Sorting, pagination, infinite scroll
  - Column selection (active columns highlighted in chat)
  - Row selection (active rows for follow-up queries)
- ✅ SQL syntax highlighting
- ✅ Chart rendering (Bar, Line, Pie)
- ✅ Tutorial mode (interactive onboarding)
- ✅ Context-aware prompts (knows selected columns/rows)
- ✅ Query metadata (description, tags, save to dashboard)
- ✅ Share functionality

**Data Flow**:
```
User Input → createRequest() → Backend InteractiveFlow
    ↓
Polling (pollForResponse) every 2s
    ↓
Request status: pending → processing → completed
    ↓
Update ChatSessionProvider state → Re-render
```

**Limitations**:
- ⚠️ Still uses polling (not SSE) - can miss intermediate updates
- ⚠️ No real-time progress indication
- ⚠️ Large result sets cause UI lag
- ⚠️ Chat history gets long (no pagination)

**Status**: 🟢 **Current primary interface, actively maintained**

---

### v1.5 Grid: Chart-Focused Interface (`/grid/[id]`)

**Timeline**: Mid-Late 2024  
**Backend Flow**: InteractiveFlow

**Architecture**:
- Page: `apps/web/app/grid/[id]/page.tsx`
- Layout: Minimal (no heavy navigation)
- Contexts: **`SessionProvider` (SSE)**, `GridSessionProvider`, `AppProvider`
- Components: `InteractiveDashboard` (chart-focused variant), `ChatContainer`
- Update Mechanism: **SSE (Server-Sent Events)** via EventSource
- State: Similar to `/query/[id]` but with SSE integration

**Features**:
- ✅ Real-time updates via SSE
- ✅ Chart types: Bar, Line, Pie
- ✅ Column/row selection
- ✅ Context-aware chat
- ✅ Auto-reconnect on connection loss

**SSE Event Types**:
```typescript
"connected" - Initial connection
"request_update" - Request status changed (pending → processing → completed)
"error" - Connection or processing error
```

**Data Flow**:
```
User Input → createRequest() → Backend InteractiveFlow
    ↓
SSE connection (/api/apegpt/sse/[session_id])
    ↓
Real-time events: request_update
    ↓
SessionProvider updates state → GridSessionProvider re-renders
```

**Advantages over `/query/[id]`**:
- ✅ Real-time progress updates
- ✅ No polling overhead
- ✅ More responsive UX

**Limitations**:
- ⚠️ Chart-focused, less emphasis on table
- ⚠️ Minimal navigation (less discoverable)
- ⚠️ SSE implementation is basic (v1 SSE, not v2 hybrid SSE)

**Status**: 🟡 **Active, but secondary to `/query/[id]`**

---

### Query-Only Interface (`/q/[id]`)

**Timeline**: 2024  
**Backend**: Direct query fetch (no agentic flows)

**Architecture**:
- Page: `apps/web/app/q/[id]/page.tsx`
- Context: `QueryDataProvider`
- Components: `QueryContainer` (read-only)
- Update Mechanism: None (static data)

**Features**:
- ✅ Shareable URLs
- ✅ OpenGraph metadata (social previews)
- ✅ Minimal auth (public or permissioned)
- ✅ Query metadata display
- ✅ Clean, distraction-free view

**Use Cases**:
- Sharing analysis results
- Embedding in external sites
- Immutable query results
- Public dashboards

**Limitations**:
- ❌ No chat or query refinement
- ❌ No agentic flows
- ❌ Read-only (no editing)

**Status**: 🟢 **Stable, serves specific use case**

---

### Dashboard Interface (`/(dash)/[[...section]]`)

**Timeline**: Late 2024  
**Backend**: Payload CMS + multiple queries

**Architecture**:
- Page: `apps/web/app/(dash)/[[...section]]/page.tsx`
- Contexts: `AppProvider`, `ItemViewContext`
- Components: `DashboardGrid`, `DashboardItem`, `DashboardTableItem`, `DashboardChartItem`
- Data Source: **Payload CMS** (fetches dashboard definitions)

**Routes**:
- `/` - Home dashboard
- `/tokens` - Token analytics
- `/trends` - Market trends
- `/traders` - Trader analytics
- `/user/*` - User-specific dashboards

**Features**:
- ✅ Curated query collections
- ✅ Grid layout (responsive)
- ✅ Table and chart items
- ✅ Dynamic loading from CMS
- ✅ View switcher (table ↔ chart)

**Limitations**:
- ⚠️ Static content (no real-time updates)
- ⚠️ CMS dependency (external service)

**Status**: 🟢 **Active, serves marketing/product use case**

---

## 3. API Integration

### Backend API Client

**File**: `apps/web/app/lib/gptAPI.ts`

**Base URL**: `process.env.APEGPT_API_URL` (Flow Manager backend)

**Type Generation**:
- OpenAPI spec from Flow Manager: `fm-app` generates OpenAPI schema
- Generated types: `apps/web/app/api/apegpt/types.gen.ts`
- Command: `npm run generate` or `npm run generate_local`
- Library: `openapi-fetch` (type-safe fetch wrapper)

**Version Strategy**:

```typescript
// Version is sent in request body, NOT URL
version: flow === Flow.Interactive ? 2 : 1
```

**Current Mapping**:
- `Flow.Interactive` → Version 2 (InteractiveFlow backend)
- `Flow.Simple` → Version 1 (legacy)
- `Flow.Multistep` → Version 1 (legacy)

### Key API Functions

**Sessions**:
```typescript
createUserSession({ name, tags })
getUserSessions()
getUserSession({ sessionId })
updateUserSession({ sessionId, name, tags })
createLinkedUserSession({ name, tags, parentId, flow, request, model, db, refs })
```

**Requests**:
```typescript
createUserRequest({ sessionId, request, requestType, flow, model, db, refs, queryId })
createUserRequestFromQuery({ sessionId, queryId })
updateUserRequest({ requestId, data })
getSingleUserRequest({ sessionId, seqNum })
getAllUserRequestsForSession({ sessionId })
```

**Queries**:
```typescript
getQuery({ queryId })
```

### Backend Endpoints (v1 API)

All current requests use `/api/v1/*` endpoints:

- `POST /api/v1/session` - Create session
- `POST /api/v1/session/{id}` - Update session
- `GET /api/v1/session/{id}` - Get session
- `GET /api/v1/sessions` - List user sessions
- `POST /api/v1/request/{session_id}` - Create request
- `GET /api/v1/request/{session_id}/{seq_num}` - Get single request
- `GET /api/v1/session/get_requests/{session_id}` - Get all requests
- `GET /api/v1/sse/{session_id}` - SSE connection (v1 SSE)
- `GET /api/v1/query/{query_id}` - Get query metadata
- `POST /api/v1/request/{session_id}/for_query/{query_id}` - Create request for query
- `POST /api/v1/request/{session_id}/from_query/{query_id}` - Clone from query

### Backend v2 API (Under Development)

**Git Status** shows untracked v2 API files:
```
?? apps/fm-app/fm_app/api/v1/
?? apps/fm-app/fm_app/api/v2/
```

This indicates the backend is being restructured with proper v1/v2 route modules.

**Expected v2 Endpoints** (based on earlier v2 work):
- `POST /api/v2/sessions` - Create session
- `POST /api/v2/sessions/{id}/messages` - Send message
- `GET /api/v2/sessions/{id}/messages` - List messages
- `GET /api/v2/sessions/{id}/stream` - **Hybrid SSE endpoint** (EventBus + PostgreSQL NOTIFY)

---

## 4. State Management

### Global Context Providers

**Root Layout** (`apps/web/app/layout.tsx`):

```tsx
<AppRouterCacheProvider>          // MUI cache
  <FlexibleThemeProvider>          // Theme (light/dark)
    <UserProvider>                 // Auth0 user
      <SWRProvider>                // SWR config
        <AppProvider>              // Global app state
          {children}
        </AppProvider>
      </SWRProvider>
    </UserProvider>
  </FlexibleThemeProvider>
</AppRouterCacheProvider>
```

### Route-Specific Contexts

#### `AppContext` (Global App State)

**File**: `apps/web/app/contexts/App/index.tsx`

**Scope**: All routes

**State**:
```typescript
{
  // Settings
  model: Model,                    // LLM model selection
  flow: Flow,                      // Flow type (Simple, Multistep, Interactive)
  db: DB,                          // Database profile (Legacy, NWH, V2)
  
  // UI State
  dialogOpen: boolean,
  navOpen: boolean,
  contextDrawerOpen: boolean,
  
  // Tab Management
  activeTab: number,
  
  // Edit Mode
  editMode: boolean
}
```

**Actions**:
```typescript
setModel(model: Model)
setFlow(flow: Flow)
setDb(db: DB)
setDialogOpen(open: boolean)
setNavOpen(open: boolean)
setContextDrawerOpen(open: boolean)
setActiveTab(tab: number)
setEditMode(enabled: boolean)
```

---

#### `ChatSessionProvider` (Primary Query Interface)

**File**: `apps/web/app/contexts/ChatSession/index.tsx`

**Used by**: `/query/[id]` route

**State**:
```typescript
{
  // Session Data
  session: UserSession,
  requests: UserRequest[],         // Chat history (all requests in session)
  
  // Query Data
  queryData: QueryData,            // Current query result (columns, data, SQL)
  queryMetadata: QueryMetadata,    // Description, tags, etc.
  
  // UI State
  activeColumns: string[],         // Selected columns (for context-aware prompts)
  activeRows: number[],            // Selected rows
  activeRowsValues: Record<string, any>[],
  
  // Data Grid State
  sortModel: GridSortModel,
  paginationModel: GridPaginationModel,
  
  // Loading States
  loading: boolean,
  error: string | null,
  
  // Infinite Scroll
  hasMore: boolean,
  loadingMore: boolean
}
```

**Actions**:
```typescript
sendMessage(request: string)        // Send user message, poll for response
setActiveColumns(columns: string[])
setActiveRows(rows: number[])
setSortModel(model: GridSortModel)
setPaginationModel(model: GridPaginationModel)
loadMore()                          // Infinite scroll
refreshData()                       // Re-fetch query data
```

**Update Mechanism**: **Polling**

```typescript
// Poll every 2 seconds until request completes
const pollForResponse = async (sessionId, seqNum) => {
  while (true) {
    const request = await getSingleUserRequest({ sessionId, seqNum });
    
    if (request.status === "completed" || request.status === "failed") {
      return request;
    }
    
    await sleep(2000);
  }
};
```

---

#### `GridSessionProvider` (Grid Interface with SSE)

**File**: `apps/web/app/contexts/GridSession/index.tsx`

**Used by**: `/grid/[id]` route

**State**: Similar to `ChatSessionProvider` but with SSE integration

**Update Mechanism**: **SSE (Server-Sent Events)**

```typescript
// Uses SessionProvider for SSE connection
<SessionProvider sessionId={sessionId}>
  <GridSessionProvider>
    {children}
  </GridSessionProvider>
</SessionProvider>
```

---

#### `SessionProvider` (SSE Connection Manager)

**File**: `apps/web/app/contexts/SessionStatus/SessionContext.tsx`

**Used by**: `/grid/[id]` route

**Purpose**: Manage SSE connection for real-time updates

**State**:
```typescript
{
  connectionState: "disconnected" | "connecting" | "connected" | "error",
  lastEvent: SSEEvent | null,
  error: string | null
}
```

**SSE Event Types**:
```typescript
type SSEEventType = "connected" | "request_update" | "error";

interface SSEEvent {
  type: SSEEventType;
  data: {
    session_id: string;
    request_id?: string;
    status?: "pending" | "processing" | "completed" | "failed";
    message?: string;
  };
}
```

**Connection Management**:
```typescript
// Auto-reconnect on failure
const MAX_RETRIES = 5;
const RETRY_DELAY_MS = 2000;

useEffect(() => {
  const eventSource = new EventSource(`/api/apegpt/sse/${sessionId}`);
  
  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    setLastEvent(data);
  };
  
  eventSource.onerror = () => {
    if (retries < MAX_RETRIES) {
      setTimeout(() => reconnect(), RETRY_DELAY_MS);
    }
  };
  
  return () => eventSource.close();
}, [sessionId, retries]);
```

---

#### `QueryDataProvider` (Read-Only Queries)

**File**: `apps/web/app/contexts/QueryData/index.tsx`

**Used by**: `/q/[id]` route

**State**:
```typescript
{
  queryData: QueryData,
  queryMetadata: QueryMetadata,
  loading: boolean,
  error: string | null
}
```

**Features**:
- One-time fetch (no updates)
- No chat or agentic flows
- Minimal state

---

#### `TutorialProvider` (Interactive Tutorial)

**File**: `apps/web/app/contexts/Tutorial/index.tsx`

**Used by**: `/query/[id]` route

**State**:
```typescript
{
  active: boolean,
  currentStep: number,
  completed: boolean,
  steps: TutorialStep[]
}
```

**Features**:
- Step-by-step onboarding
- Highlights UI elements
- Tracks progress
- Skip/resume functionality

---

## 5. Real-Time Updates (SSE)

### Current SSE Implementation (v1 SSE)

**Used by**: `/grid/[id]` route via `SessionProvider`

**Endpoint**: `GET /api/v1/sse/{session_id}`

**Flow**:
```
Frontend (EventSource) → /api/apegpt/sse/[session_id] → Flow Manager /api/v1/sse/{session_id}
```

**Event Types** (v1):
```typescript
{
  type: "connected",
  data: { session_id: string }
}

{
  type: "request_update",
  data: {
    session_id: string,
    request_id: string,
    status: "pending" | "processing" | "completed" | "failed",
    message?: string
  }
}

{
  type: "error",
  data: { message: string }
}
```

**Limitations**:
- ⚠️ Coarse-grained (only request status changes)
- ⚠️ No progress indication (thinking, validating, executing)
- ⚠️ PostgreSQL NOTIFY only (no transient events)

---

### V2 Hybrid SSE (Backend Ready, Not in Frontend Yet)

**Backend Endpoint**: `GET /api/v2/sessions/{id}/stream`

**Event Types** (v2):
```typescript
// Connection event
{
  event: "connected",
  data: { session_id: string, mode: "hybrid" }
}

// Transient progress (from EventBus)
{
  event: "agent_status",
  data: {
    status: "thinking" | "validating" | "executing" | ...,
    step: string,
    progress: number
  }
}

// Persistent state changes (from PostgreSQL NOTIFY)
{
  event: "message_update",
  data: {
    message_id: string,
    session_id: string,
    status: "pending" | "processing" | "completed" | "failed",
    has_error: boolean
  }
}

// Keepalive
{
  event: "ping",
  data: { timestamp: string }
}
```

**Advantages**:
- ✅ Rich progress updates (EventBus)
- ✅ Reliable state persistence (PostgreSQL NOTIFY)
- ✅ Hybrid resilience (both sources)
- ✅ Detailed agent lifecycle events

**Frontend Integration Status**: ❌ Not yet integrated (backend deployed, waiting for frontend work)

---

## 6. Authentication

### Strategy: Hybrid Auth (Auth0 + Guest Tokens)

**Authenticated Users**:
- Auth0 OAuth flow
- JWT tokens
- Full feature access

**Guest Users**:
- Anonymous UUID (`uid` cookie)
- Guest token generated by backend
- Free quota limits
- Prompt to sign up after quota

### Auth Flow

```
User visits app
    ↓
Check for Auth0 session
    ↓
If authenticated → Use Auth0 token
    ↓
If not → Check for `uid` cookie
    ↓
If no `uid` → Generate UUID, set cookie
    ↓
Request guest token from `/api/auth/guest`
    ↓
Backend generates guest JWT
    ↓
Frontend stores in memory (not persisted)
    ↓
Include in API requests: Authorization: Bearer <token>
```

### Token Usage

**All API requests include auth header**:
```typescript
headers: {
  Authorization: `Bearer ${token}`
}
```

**Backend validates**:
- Auth0 JWT: Full access
- Guest JWT: Quota-limited access

**Quota Check**:
- Guest users have free query limit
- Backend tracks usage by `uid`
- Frontend shows quota usage
- "Request Access" flow for more

### Auth Components

**`UserProvider`** (`@auth0/nextjs-auth0`):
- Wraps app in root layout
- Provides `useUser()` hook
- Handles login/logout

**`LoginPrompt`**:
- Shown when quota exceeded
- "Sign in" or "Request Access" options

**`UserProfileMenu`**:
- User avatar dropdown
- Account settings
- Logout

---

## 7. Component Architecture

### Component Organization

```
apps/web/app/
├── components/          // Shared components
│   ├── chat/           // Chat UI
│   ├── data-grid/      // Table components
│   ├── dashboard/      // Dashboard items
│   ├── navigation/     // Top nav, side nav
│   └── query/          // Query-specific UI
│
├── contexts/           // React contexts (state management)
│   ├── App/
│   ├── ChatSession/
│   ├── GridSession/
│   ├── SessionStatus/
│   ├── QueryData/
│   └── Tutorial/
│
├── lib/                // Utilities
│   ├── gptAPI.ts       // Backend API client
│   ├── types.ts        // Shared types
│   └── utils.ts        // Helpers
│
├── api/                // Next.js API routes (proxies)
│   ├── apegpt/
│   ├── auth/
│   ├── dashboards/
│   └── charts/
│
└── (routes)/           // App Router pages
    ├── chat/[id]/
    ├── query/[id]/
    ├── grid/[id]/
    ├── q/[id]/
    └── (dash)/
```

### Key Component Examples

#### `DataTable` (MUI X DataGrid Pro)

**File**: `apps/web/app/components/data-grid/DataTable.tsx`

**Features**:
- Virtualized scrolling (handles 100k+ rows)
- Sorting (client-side and server-side)
- Pagination
- Column selection
- Row selection
- Custom cell rendering (`StyledValue`)
- Infinite scroll integration
- Export to CSV

**Props**:
```typescript
{
  columns: Column[],              // Column definitions
  data: any[],                    // Row data
  loading: boolean,
  onSortModelChange: (model) => void,
  onPaginationModelChange: (model) => void,
  onSelectionChange: (rows) => void,
  activeColumns: string[],        // Highlighted columns
  activeRows: number[],           // Highlighted rows
  infiniteScroll: boolean,        // Enable infinite scroll
  onLoadMore: () => void
}
```

---

#### `ChatContainer` (Chat Interface)

**File**: `apps/web/app/components/chat/chat-container/index.tsx`

**Features**:
- Message history rendering
- User input box
- Loading indicators
- Error messages
- Context-aware prompts (knows selected columns/rows)
- Auto-scroll to bottom
- Markdown rendering

**Props**:
```typescript
{
  session: UserSession,
  requests: UserRequest[],
  onSendMessage: (message: string) => void,
  loading: boolean,
  activeColumns: string[],        // Show in input hint
  activeRows: number[]            // Show in input hint
}
```

---

#### `InteractiveDashboard` (Main Query Interface)

**File**: `apps/web/app/components/query/InteractiveDashboard.tsx`

**Features**:
- Tabbed interface (Table / SQL / Chart)
- Data grid integration
- SQL syntax highlighting
- Chart rendering (Bar, Line, Pie)
- Query metadata editor
- Share/save controls

**Variants**:
- `/query/[id]` version: Table-focused, 3 tabs
- `/grid/[id]` version: Chart-focused, grid layout

---

#### `StyledValue` (Cell Formatter)

**File**: `apps/web/app/components/data-grid/StyledValue.tsx`

**Purpose**: Format cell values based on type

**Supported Types**:
- Blockchain addresses (truncate, link to explorer)
- Transaction signatures (truncate, link)
- URLs (clickable links)
- Large numbers (formatting with commas)
- Dates (ISO → human-readable)
- Booleans (✓/✗)
- Null/undefined (empty cell)

**Example**:
```typescript
// Address: 0x1234...5678 (clickable, opens explorer)
// Number: 1,234,567.89
// Date: Nov 9, 2024 10:30 AM
```

---

## 8. Data Fetching Patterns

### Server Components (Default)

**Pattern**: Fetch data at page level, pass to client components

```typescript
// app/query/[id]/page.tsx
export default async function QueryPage({ params }) {
  const session = await getUserSession({ sessionId: params.id });
  const requests = await getAllUserRequestsForSession({ sessionId: params.id });
  
  return <QueryPageClient session={session} requests={requests} />;
}
```

**Advantages**:
- Rendered on server (faster initial load)
- SEO-friendly
- No client-side loading state

---

### Client Components with SWR

**Pattern**: Use SWR for client-side data fetching with caching

```typescript
import useSWR from 'swr';

function QueryData({ queryId }) {
  const { data, error, mutate } = useSWR(
    `/api/apegpt/data/${queryId}`,
    fetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: true
    }
  );
  
  if (error) return <Error />;
  if (!data) return <Loading />;
  
  return <DataTable data={data} />;
}
```

**SWR Config** (`apps/web/app/contexts/SWR/index.tsx`):
```typescript
{
  revalidateOnFocus: false,
  revalidateOnReconnect: true,
  shouldRetryOnError: false,
  dedupingInterval: 2000
}
```

---

### Server Actions (Mutations)

**File**: `apps/web/app/actions.tsx`

**Pattern**: Use `"use server"` for mutations

```typescript
"use server";

export async function createSession({ name, tags }) {
  const token = await getAuthToken();
  
  const session = await createUserSession({ name, tags }, token);
  
  revalidatePath('/');
  
  return session;
}
```

**Usage in Client Components**:
```typescript
import { createSession } from '@/app/actions';

function NewSessionButton() {
  const handleCreate = async () => {
    const session = await createSession({ name: "New Session" });
    router.push(`/query/${session.id}`);
  };
  
  return <Button onClick={handleCreate}>New Session</Button>;
}
```

---

### Real-Time Updates (SSE)

**Pattern**: EventSource API for streaming updates

```typescript
useEffect(() => {
  const eventSource = new EventSource(`/api/apegpt/sse/${sessionId}`, {
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  
  eventSource.addEventListener('request_update', (event) => {
    const data = JSON.parse(event.data);
    
    // Update local state
    setRequests(prev => 
      prev.map(req => 
        req.id === data.request_id 
          ? { ...req, status: data.status } 
          : req
      )
    );
  });
  
  return () => eventSource.close();
}, [sessionId]);
```

---

## 9. Current Limitations & Pain Points

### Performance Issues

1. **Large Result Sets**
   - MUI DataGrid Pro struggles with 10k+ rows
   - Infinite scroll helps but not enough
   - No server-side pagination yet

2. **Polling Overhead** (`/query/[id]`)
   - Polls every 2 seconds
   - Creates unnecessary backend load
   - Misses intermediate updates

3. **Chat History Growth**
   - Long sessions (50+ messages) cause lag
   - No message pagination
   - Re-renders entire history on update

### UX Inconsistencies

1. **Two Update Mechanisms**
   - `/query/[id]` uses polling
   - `/grid/[id]` uses SSE
   - Confusing for users (different behaviors)

2. **Disconnected Interfaces**
   - Chat and data grid feel separate
   - No visual connection between selected columns and chat
   - Limited context awareness

3. **Limited Progress Feedback**
   - Generic "Loading..." spinners
   - No indication of what step is running
   - Users don't know if query is slow or stuck

### Technical Debt

1. **Duplicate Code**
   - `ChatSessionProvider` vs. `GridSessionProvider` (90% similar)
   - Multiple `InteractiveDashboard` variants
   - Copy-pasted SSE logic

2. **Mixed Patterns**
   - Some components use contexts, others prop drilling
   - Server components mixed with client components inconsistently
   - API client (`gptAPI.ts`) used alongside `fetch()` calls

3. **No Error Boundaries**
   - Errors crash entire route
   - No graceful degradation
   - Limited error recovery

### Missing Features

1. **No Message Editing**
   - Can't edit past messages
   - Can't delete messages
   - Can't re-run with modifications

2. **Limited Collaboration**
   - No session sharing (except `/q/[id]`)
   - No multi-user sessions
   - No comments or annotations

3. **Poor Mobile Experience**
   - Data grid doesn't work well on mobile
   - Chat interface cramped
   - No responsive chart sizing

---

## 10. V2 Readiness Assessment

### Backend V2 Status

✅ **API Modules Ready**:
- `apps/fm-app/fm_app/api/v1/` (stable)
- `apps/fm-app/fm_app/api/v2/` (new, message-based)

✅ **V2 Architecture**:
- Message-based (vs. request/response)
- Hybrid SSE (EventBus + PostgreSQL NOTIFY)
- Rich event types (30+ AgentEventTypes)
- Session → Messages model

✅ **Deployed**:
- Timeout monitor (crash recovery)
- PostgreSQL NOTIFY trigger
- Celery auto-retry
- Migration applied

### Frontend V2 Gaps

❌ **No V2 Route Structure**:
- Still using `/query/[id]`, `/grid/[id]`
- No `/v2/query/[id]` or version-aware routing

❌ **No V2 API Client**:
- `gptAPI.ts` only calls v1 endpoints
- No types for v2 messages
- No v2 OpenAPI client generation

❌ **No V2 Context Providers**:
- `ChatSessionProvider` is v1-style (requests)
- Need `MessageSessionProvider` for v2 (messages)

❌ **No Hybrid SSE Integration**:
- `SessionProvider` uses v1 SSE
- Need new provider for v2 hybrid SSE

❌ **No Notebook-Style UX**:
- Chat bubbles (not cells)
- No execution order indicators
- No markdown note cells
- No output collapsing

### What Needs to Be Built

#### Phase 1: V2 API Integration (2 weeks)

1. **Generate V2 Types**
   - Update OpenAPI spec generation to include v2 endpoints
   - Generate `apps/web/app/api/apegpt-v2/types.gen.ts`

2. **Create V2 API Client**
   - `apps/web/app/lib/gptAPI-v2.ts`
   - Functions: `createV2Session`, `sendMessage`, `getMessages`, `streamEvents`

3. **Build V2 SSE Provider**
   - `apps/web/app/contexts/V2Session/SessionProvider.tsx`
   - Connect to `/api/v2/sessions/{id}/stream`
   - Handle 3 event types: `connected`, `agent_status`, `message_update`

4. **Create MessageSessionProvider**
   - `apps/web/app/contexts/V2Session/MessageSessionProvider.tsx`
   - State: `session`, `messages[]` (not `requests[]`)
   - Actions: `sendMessage`, `deleteMessage`, `updateMessage`

#### Phase 2: V2 Route (2 weeks)

5. **New Route: `/v2/query/[id]`**
   - Duplicate `/query/[id]` structure
   - Replace `ChatSessionProvider` with `MessageSessionProvider`
   - Replace polling with v2 SSE

6. **Feature Flag**
   - Environment variable: `ENABLE_V2_ROUTES`
   - Show "Try V2" button in v1 interface
   - Allow users to switch

7. **Parallel Running**
   - Keep v1 routes stable
   - V2 routes beta mode
   - User testing with small group

#### Phase 3: Notebook-Style UX (3 weeks)

8. **Cell-Based Message Interface**
   - Replace chat bubbles with notebook cells
   - Components: `MessageCell`, `UserInputCell`, `AssistantResponseCell`, `NoteCell`

9. **Execution Order Indicators**
   - Add `[1]`, `[2]` badges
   - Visual states: `[ ]` (pending), `[*]` (executing), `[1]` (complete), `[!]` (error)

10. **Rich Progress Events**
    - Show agent status from EventBus
    - "Thinking...", "Validating SQL...", "Executing query..."
    - Progress bar for long-running steps

11. **Markdown Note Cells**
    - New message kind: `MessageKind.NOTE`
    - Markdown editor component
    - "Add Note" button between messages

12. **Collapsible Outputs**
    - Fold large tables
    - "Show 20 rows" → "Show all 1,234 rows"
    - Persist collapsed state

#### Phase 4: Advanced Features (4+ weeks)

13. **Message Editing**
    - Edit past user messages
    - Re-run from edited message
    - Branch conversations

14. **Control Endpoints**
    - Cancel running messages
    - Interrupt long queries
    - Pause/resume

15. **Keyboard Shortcuts**
    - Shift+Enter: Run cell
    - Cmd+Enter: Run and insert
    - Esc: Command mode

16. **Export to Notebook**
    - Session → `.ipynb` conversion
    - Download button
    - Share as Jupyter notebook

---

## Next Steps for V2 Development

### Immediate Actions (This Week)

1. ✅ **Document current architecture** (this file)
2. **Create V2 development plan** (separate doc)
3. **Set up V2 workspace**:
   - Create `apps/web/app/v2/` directory
   - Copy base components from `/query`
   - Set up v2 contexts

4. **Generate V2 OpenAPI client**:
   ```bash
   cd apps/web
   npm run generate_local  # Point to local fm-app with v2 routes
   ```

5. **Build minimal v2 route**:
   - `/v2/query/[id]` with basic message rendering
   - Connect to v2 SSE endpoint
   - Prove hybrid SSE works end-to-end

### This Sprint (2 Weeks)

6. **V2 SSE Integration**
   - Build `V2SessionProvider`
   - Handle all 3 event types
   - Test reconnection logic

7. **MessageSessionProvider**
   - Port `ChatSessionProvider` to message-based model
   - Send/receive messages (not requests)
   - Update on `message_update` events

8. **Parallel Route Testing**
   - Deploy v2 route to staging
   - User testing with team
   - Gather feedback

### Next Sprint (2 Weeks)

9. **Notebook UX Prototype**
   - Build cell components
   - Execution order badges
   - Progress indicators

10. **Feature Parity**
    - Match all `/query/[id]` features
    - Data grid, SQL view, charts
    - Share, save, metadata

### Month 2

11. **Advanced UX**
    - Markdown cells
    - Collapsible outputs
    - Keyboard shortcuts

12. **Beta Launch**
    - Open v2 to all users
    - Monitor performance
    - Fix bugs

### Month 3

13. **Deprecation Plan**
    - Migrate users from v1 to v2
    - Sunset old routes
    - Clean up legacy code

---

## Conclusion

The Semantic Grid web app has evolved through multiple generations of UX (v1 → v1.5 → v2 incoming), each building on lessons learned. The current primary interface (`/query/[id]`) is feature-rich but uses polling instead of real-time updates. The backend v2 API is ready with a message-based architecture and hybrid SSE, but the frontend needs significant work to integrate it.

The path forward is clear:
1. Build v2 API client and types
2. Create v2 route with message-based contexts
3. Integrate hybrid SSE for real-time updates
4. Gradually adopt notebook-style UX patterns
5. Run v1 and v2 in parallel during transition
6. Migrate users once v2 reaches feature parity

This will result in a modern, responsive, notebook-like interface for data analysis that leverages the full power of the v2 backend architecture.

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-09  
**Next Review**: Before v2 development kickoff
