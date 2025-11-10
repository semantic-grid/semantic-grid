# V2 Frontend Architecture

**Date**: 2025-11-09  
**Status**: Reference for v2 implementation

## Overview

V2 frontend architecture for Semantic Grid, integrating with the deployed v2 backend (message-based API with hybrid SSE).

---

## Architecture Diagram

```
Frontend (Next.js)
├── V2SessionProvider (SSE Manager)
│   ├── EventSource → /api/v2/sessions/{id}/stream
│   ├── Handles: connected, agent_status, message_update, ping
│   └── Auto-reconnect with backoff
│
├── MessageSessionProvider (State)
│   ├── Messages array (not requests)
│   ├── sendMessage() → POST /api/v2/sessions/{id}/messages
│   ├── updateMessage() → PATCH /api/v2/sessions/{id}/messages/{msg_id}
│   └── deleteMessage() → DELETE /api/v2/sessions/{id}/messages/{msg_id}
│
└── Notebook UI Components
    ├── MessageCell (base)
    ├── UserInputCell
    ├── AssistantCell
    ├── NoteCell (markdown)
    └── AgentProgress (real-time status)

Backend (Flow Manager - deployed)
├── POST /api/v2/sessions
├── POST /api/v2/sessions/{id}/messages
├── GET  /api/v2/sessions/{id}/messages
└── GET  /api/v2/sessions/{id}/stream (Hybrid SSE)
    ├── EventBus (transient: agent_status)
    └── PostgreSQL NOTIFY (persistent: message_update)
```

---

## Event Flow

```
User sends message
    ↓
POST /api/v2/sessions/{id}/messages
    ↓
PostgreSQL: INSERT message (status=PENDING)
    ↓
PostgreSQL NOTIFY → Frontend SSE: message_update
    ↓
Celery worker picks up message
    ↓
Worker publishes to EventBus:
    - agent_status: "intent_analyzing"
    - agent_status: "sql_validating"
    - agent_status: "query_executing"
    ↓
Frontend SSE receives all agent_status events
    ↓
PostgreSQL: UPDATE message (status=COMPLETED)
    ↓
PostgreSQL NOTIFY → Frontend SSE: message_update (final)
```

---

## Directory Structure

```
apps/web/
├── app/
│   ├── v2/                          # V2 routes
│   │   └── query/[id]/
│   │       └── page.tsx
│   │
│   ├── components/v2/               # V2 components
│   │   ├── cells/
│   │   │   ├── MessageCell.tsx      # Base cell
│   │   │   ├── UserInputCell.tsx
│   │   │   ├── AssistantCell.tsx
│   │   │   └── NoteCell.tsx
│   │   └── progress/
│   │       └── AgentProgress.tsx    # Real-time progress
│   │
│   ├── contexts/V2Session/
│   │   ├── SessionProvider.tsx      # SSE connection
│   │   └── MessageSession.tsx       # Message state
│   │
│   ├── lib/
│   │   ├── gptAPI-v2.ts             # V2 API client
│   │   └── v2-types.ts              # Generated types
│   │
│   └── api/apegpt-v2/               # V2 proxy routes
│       └── stream/[session_id]/route.ts
```

---

## Core Components

### V2SessionProvider (SSE Manager)

**File**: `apps/web/app/contexts/V2Session/SessionProvider.tsx`

**Responsibilities**:
- Establish SSE connection to `/api/v2/sessions/{id}/stream`
- Handle 3 event types: `connected`, `agent_status`, `message_update`
- Auto-reconnect on failure (exponential backoff)
- Expose connection state to consumers

**State**:
```typescript
{
  connectionState: 'disconnected' | 'connecting' | 'connected' | 'error',
  lastAgentStatus: AgentStatusEvent | null,
  lastMessageUpdate: MessageUpdateEvent | null,
  error: string | null
}
```

**Key Pattern**: Uses EventSource API with auth token in query param (SSE doesn't support headers)

---

### MessageSessionProvider (State Manager)

**File**: `apps/web/app/contexts/V2Session/MessageSession.tsx`

**Responsibilities**:
- Manage messages array
- CRUD operations (send, update, delete)
- Optimistic updates for better UX
- Listen to SSE events and update state

**State**:
```typescript
{
  messages: Message[],
  loading: boolean,
  error: string | null
}
```

**Actions**:
```typescript
sendMessage(content: string, kind?: string)
updateMessage(messageId: string, updates: { content?: string })
deleteMessage(messageId: string)
refreshMessages()
```

**Key Pattern**: 
- Optimistic updates (add message locally before API confirms)
- SSE events update existing messages (status changes)
- New messages trigger fetch (to get full details)

---

### MessageCell (Notebook-Style UI)

**File**: `apps/web/app/components/v2/cells/MessageCell.tsx`

**Responsibilities**:
- Render message as notebook cell (not chat bubble)
- Show execution order badge: `[1]`, `[2]`, `[*]`, `[!]`
- Cell-level actions: re-run, fold, edit, delete
- Collapsible outputs for large results

**Props**:
```typescript
{
  message: Message,
  executionOrder: number,        // [1], [2], etc.
  onRerun?: () => void,
  onDelete?: () => void,
  onEdit?: () => void,
  onFold?: () => void,
  collapsed?: boolean
}
```

**Visual States**:
- `[ ]` - Pending (not executed)
- `[*]` - Processing (animated spinner)
- `[1]` - Completed (execution order number)
- `[!]` - Failed (error state)

---

### AgentProgress (Real-Time Status)

**File**: `apps/web/app/components/v2/progress/AgentProgress.tsx`

**Responsibilities**:
- Display current agent step from EventBus events
- Show progress indicator
- Map agent event types to human-readable labels

**Props**:
```typescript
{
  agentStatus: {
    type: string,        // AgentEventType
    step?: string,
    progress?: number    // 0.0 - 1.0
  } | null
}
```

**Event Type Labels**:
```typescript
{
  intent_analyzing: "Analyzing your request...",
  plan_drafting: "Creating execution plan...",
  sql_validating: "Validating SQL query...",
  query_executing: "Running query...",
  data_processing: "Processing results..."
}
```

---

## API Client

### V2 API Client

**File**: `apps/web/app/lib/gptAPI-v2.ts`

**Base Functions**:
```typescript
// Sessions
createV2Session(req, token): Promise<Session>
getV2Session(sessionId, token): Promise<Session>

// Messages
sendMessage(sessionId, message, token): Promise<Message>
getMessages(sessionId, options, token): Promise<Message[]>
updateMessage(sessionId, messageId, updates, token): Promise<Message>
deleteMessage(sessionId, messageId, token): Promise<void>
```

**Type Safety**: Uses `openapi-fetch` with generated types from backend OpenAPI spec

**Generation**:
```bash
cd apps/web
npm run generate_local  # Generate types from local fm-app
```

---

## SSE Event Types

### Connected Event

```typescript
{
  event: "connected",
  data: {
    session_id: string,
    mode: "hybrid"
  }
}
```

### Agent Status Event (from EventBus - transient)

```typescript
{
  event: "agent_status",
  data: {
    type: string,          // AgentEventType enum
    message_id: string,
    step?: string,
    progress?: number,     // 0.0 - 1.0
    metadata?: object
  }
}
```

### Message Update Event (from PostgreSQL NOTIFY - persistent)

```typescript
{
  event: "message_update",
  data: {
    message_id: string,
    session_id: string,
    role: "user" | "assistant" | "system" | "tool",
    kind: string,          // MessageKind enum
    status: "pending" | "processing" | "completed" | "failed",
    has_error: boolean,
    created_at: number,    // Unix timestamp
    operation: "INSERT" | "UPDATE"
  }
}
```

### Ping Event (keepalive)

```typescript
{
  event: "ping",
  data: {
    timestamp: string
  }
}
```

---

## Message Kinds

```typescript
enum MessageKind {
  // User messages
  CHAT = "chat",
  INTERACTIVE_QUERY = "interactive_query",
  
  // Assistant messages
  QUERY_RESULT = "query_result",
  TABLE = "table",
  CHART = "chart",
  SQL = "sql",
  
  // System
  NOTIFICATION = "notification",
  ERROR = "error",
  
  // V2 notebook features
  NOTE = "note",              // Markdown note cell
  CODE = "code",              // Code snippet
  VISUALIZATION = "visualization"
}
```

---

## State Management Pattern

### Optimistic Updates

```typescript
// When user sends message
async function sendMessage(content: string) {
  // 1. Optimistic update (immediate UI feedback)
  const tempMessage = {
    id: `temp-${Date.now()}`,
    content,
    status: 'pending',
    created_at: new Date().toISOString()
  };
  setMessages(prev => [...prev, tempMessage]);
  
  // 2. Send to backend
  try {
    await apiSendMessage(sessionId, { content }, token);
    // Real message will arrive via SSE
  } catch (err) {
    // Rollback optimistic update on error
    setMessages(prev => prev.filter(m => m.id !== tempMessage.id));
    throw err;
  }
}
```

### SSE Event Handling

```typescript
// Update state based on SSE events
useEffect(() => {
  if (!lastMessageUpdate) return;
  
  setMessages(prev => {
    const existing = prev.find(m => m.id === lastMessageUpdate.message_id);
    
    if (existing) {
      // Update existing message status
      return prev.map(m =>
        m.id === lastMessageUpdate.message_id
          ? { ...m, status: lastMessageUpdate.status }
          : m
      );
    } else {
      // New message - fetch full details
      refreshMessages();
      return prev;
    }
  });
}, [lastMessageUpdate]);
```

---

## Notebook UX Patterns (Jupyter-Inspired)

### Cell-Based Interface

**Not This** (chat bubbles):
```
┌─────────────────────┐
│ User: Query text    │
└─────────────────────┘
┌─────────────────────┐
│ Bot: Response       │
│ [Table]             │
└─────────────────────┘
```

**This** (notebook cells):
```
┌─────────────────────────────────┐
│ [1] User Input        [⟳][×]    │
├─────────────────────────────────┤
│ Query text                      │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│ [1] Assistant         [⋮][Fold] │
├─────────────────────────────────┤
│ ⚡ Validating...        ✓        │
│ ⚡ Executing...         ✓ 3.2s   │
│                                  │
│ Response text                   │
│ ┌─────────────────────────────┐ │
│ │ [Table data]                │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

### Execution Order

- Each cell has a badge: `[1]`, `[2]`, `[3]`
- Visual states:
  - `[ ]` - Not executed
  - `[*]` - Executing (animated)
  - `[n]` - Completed (n = execution order)
  - `[!]` - Failed

### Progress Indicators

Show real-time progress from EventBus `agent_status` events:
```
⚡ Analyzing intent...      ✓
⚡ Generating SQL...         ✓
⚡ Validating query...       ✓
⚡ Executing query...        ⏳ 45% (2.3s)
```

### Collapsible Outputs

Large tables/results are collapsible:
```
┌─────────────────────────────────┐
│ Results (1,234 rows)     [Fold] │
├─────────────────────────────────┤
│ [First 20 rows shown]           │
│ ...                              │
│ [Show all 1,234 rows]           │
└─────────────────────────────────┘
```

---

## Differences from V1

| Aspect | V1 (`/query/[id]`) | V2 (`/v2/query/[id]`) |
|--------|-------------------|----------------------|
| **Data Model** | Requests (request/response) | Messages (flexible) |
| **Update Mechanism** | Polling (2s interval) | SSE (real-time) |
| **Progress** | Generic "Loading..." | Detailed steps with progress |
| **UI** | Chat bubbles | Notebook cells |
| **Execution Order** | None | Visible `[1]`, `[2]` |
| **Backend API** | `/api/v1/*` | `/api/v2/*` |
| **SSE** | v1 SSE (PostgreSQL only) | Hybrid SSE (EventBus + PostgreSQL) |
| **Event Granularity** | Coarse (request status) | Fine (agent steps) |
| **Editing** | No | Yes (edit messages, re-run) |
| **Notes** | No | Yes (markdown note cells) |

---

## Key Implementation Considerations

### SSE Connection Management

- **Auth**: Token in query param (EventSource doesn't support headers)
- **Reconnection**: Exponential backoff (2s, 4s, 8s, 16s, 32s max)
- **Max Retries**: 5 attempts before giving up
- **Keepalive**: Ping events every 30s prevent timeout
- **Cleanup**: Always close EventSource on unmount

### Performance

- **Virtualization**: Use `react-window` for long message lists (50+ messages)
- **Lazy Loading**: Load message details on-demand for collapsed cells
- **Optimistic Updates**: Immediate UI feedback, reconcile with server
- **Debouncing**: Debounce message edits to avoid excessive API calls

### Error Handling

- **Network Errors**: Retry with backoff, show reconnecting indicator
- **API Errors**: Display structured error with retry button
- **SSE Errors**: Fallback to polling if SSE fails repeatedly
- **Optimistic Update Rollback**: Remove failed optimistic updates

---

## Integration with Existing Components

### Reuse from V1

**Data Display**:
- `DataTable` (MUI X DataGrid Pro)
- `StyledValue` (cell formatter)
- `SqlView` (syntax highlighting)
- Chart components (Bar, Line, Pie)

**Navigation**:
- `TopNavClient`
- `UserProfileMenu`

**Utilities**:
- `ShareQueryUrl`
- `SaveQueryUrl`
- `CopyQueryUrl`

### New V2-Specific

**Cell Components**:
- `MessageCell`, `UserInputCell`, `AssistantCell`, `NoteCell`

**Progress Components**:
- `AgentProgress`, `StepIndicator`

**Contexts**:
- `V2SessionProvider`, `MessageSessionProvider`

**API**:
- `gptAPI-v2.ts` (v2 client)

---

## Testing Checklist

### Unit Tests

- [ ] V2SessionProvider connects and reconnects
- [ ] MessageSessionProvider CRUD operations
- [ ] Optimistic updates work correctly
- [ ] SSE event handling updates state
- [ ] MessageCell renders all states
- [ ] AgentProgress maps event types correctly

### Integration Tests

- [ ] Send message → receive agent_status events
- [ ] Send message → receive message_update events
- [ ] SSE reconnection after network failure
- [ ] Edit message → re-execution flow
- [ ] Cancel message mid-execution
- [ ] Add note cell → save → render

### E2E Tests

- [ ] Complete query flow (send → execute → results)
- [ ] Multi-message session
- [ ] Collapse/expand outputs
- [ ] Re-run past message
- [ ] Switch between v1 and v2 routes

---

## Reference Links

**Related Docs**:
- `docs/architecture/web-app-structure.md` - Current v1/v1.5 architecture
- `docs/future/jupyter-notebook-parallels.md` - Jupyter inspiration analysis
- `docs/V2_HYBRID_SSE_APPROACH.md` - Backend SSE architecture

**Backend**:
- `apps/fm-app/fm_app/api/v2/routes.py` - V2 API routes
- `apps/fm-app/fm_app/api/v2/model.py` - V2 message models
- `apps/fm-app/fm_app/workers/v2/` - V2 workers (EventBus)

**Frontend V1** (for reference):
- `apps/web/app/query/[id]/page.tsx` - Current primary interface
- `apps/web/app/contexts/ChatSession/` - V1 session provider
- `apps/web/app/contexts/SessionStatus/` - V1 SSE provider

---

**Last Updated**: 2025-11-09
