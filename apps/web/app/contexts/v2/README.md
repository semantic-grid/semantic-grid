# V2 Contexts

React contexts for Semantic Grid V2 (message-based architecture with hybrid SSE).

## Overview

These contexts manage state and real-time connections for the v2 notebook interface:

- **V2SessionProvider** - SSE connection manager (hybrid EventBus + PostgreSQL NOTIFY)
- **MessageSessionProvider** - Message state manager (CRUD operations)
- **useAgentStatus** - Current agent processing status

## Quick Start

```typescript
import {
  V2SessionProvider,
  MessageSessionProvider,
  useV2Session,
  useMessageSession,
  useAgentStatus,
} from '@/app/contexts/v2';

// In your page component
export default function NotebookPage({ params }) {
  return (
    <V2SessionProvider sessionId={params.id}>
      <MessageSessionProvider sessionId={params.id}>
        <NotebookInterface />
      </MessageSessionProvider>
    </V2SessionProvider>
  );
}

// In child components
function NotebookInterface() {
  const { connectionState } = useV2Session();
  const { messages, sendMessage, loading } = useMessageSession();
  const { isProcessing, stepLabel } = useAgentStatus();
  
  return (
    <div>
      <p>Connection: {connectionState}</p>
      {isProcessing && <p>Status: {stepLabel}</p>}
      
      {messages.map(msg => (
        <MessageCell key={msg.id} message={msg} />
      ))}
      
      <button onClick={() => sendMessage('Show top 10 transactions')}>
        Send
      </button>
    </div>
  );
}
```

## Components

### V2SessionProvider

Manages SSE connection for real-time updates.

**Props**:
```typescript
{
  sessionId: string;           // Session UUID
  children: React.ReactNode;
  autoConnect?: boolean;       // Default: true
  maxRetries?: number;         // Default: 5
  retryDelayMs?: number;       // Default: 2000
}
```

**Hook**: `useV2Session()`

Returns:
```typescript
{
  connectionState: 'disconnected' | 'connecting' | 'connected' | 'error';
  error: string | null;
  lastAgentStatus: AgentStatusEvent | null;     // Latest progress event
  lastMessageUpdate: MessageUpdateEvent | null;  // Latest message change
  reconnect: () => void;
  disconnect: () => void;
}
```

**Features**:
- Auto-reconnect with exponential backoff
- Handles hybrid SSE (EventBus + PostgreSQL NOTIFY)
- Works with Auth0 and guest tokens
- Automatic cleanup on unmount

---

### MessageSessionProvider

Manages message state with optimistic updates.

**Props**:
```typescript
{
  sessionId: string;
  children: React.ReactNode;
  initialMessages?: V2Message[];
  autoLoad?: boolean;          // Default: true
}
```

**Hook**: `useMessageSession()`

Returns:
```typescript
{
  messages: V2Message[];
  loading: boolean;
  error: string | null;
  
  // Actions
  sendMessage: (content: string, kind?: MessageKind) => Promise<void>;
  refreshMessages: () => Promise<void>;
  
  // Helpers
  userMessages: V2Message[];
  assistantMessages: V2Message[];
  latestMessage: V2Message | null;
}
```

**Features**:
- Optimistic updates (instant UI feedback)
- SSE integration (auto-updates from events)
- Message filtering helpers
- Automatic refresh on new messages

---

### useAgentStatus

Get current agent processing status.

**Hook**: `useAgentStatus()`

Returns:
```typescript
{
  isProcessing: boolean;
  currentStep: string | null;      // e.g., "sql_validating"
  stepLabel: string | null;        // e.g., "Validating SQL query"
  progress: number | null;         // 0.0 - 1.0
  metadata: Record<string, any> | null;
}
```

**Step Labels**:
```typescript
{
  intent_analyzing: "Analyzing your request",
  plan_drafting: "Creating execution plan",
  sql_validating: "Validating SQL query",
  query_executing: "Running query",
  data_processing: "Processing results",
  // ... and 20+ more
}
```

## Usage Examples

### Basic Setup

```typescript
// app/nb/[id]/page.tsx
import { V2SessionProvider, MessageSessionProvider } from '@/app/contexts/v2';

export default function NotebookPage({ params }: { params: { id: string } }) {
  return (
    <V2SessionProvider sessionId={params.id}>
      <MessageSessionProvider sessionId={params.id}>
        <NotebookUI />
      </MessageSessionProvider>
    </V2SessionProvider>
  );
}
```

### Send Message

```typescript
function MessageInput() {
  const { sendMessage, loading } = useMessageSession();
  const [input, setInput] = useState('');
  
  const handleSend = async () => {
    await sendMessage(input, 'interactive_query');
    setInput('');
  };
  
  return (
    <div>
      <input value={input} onChange={e => setInput(e.target.value)} />
      <button onClick={handleSend} disabled={loading}>
        Send
      </button>
    </div>
  );
}
```

### Show Progress

```typescript
function ProgressIndicator() {
  const { isProcessing, stepLabel, progress } = useAgentStatus();
  
  if (!isProcessing) return null;
  
  return (
    <div>
      <p>{stepLabel}</p>
      {progress !== null && (
        <progress value={progress} max={1} />
      )}
    </div>
  );
}
```

### Connection Status

```typescript
function ConnectionIndicator() {
  const { connectionState, reconnect, error } = useV2Session();
  
  return (
    <div>
      <span>Status: {connectionState}</span>
      {connectionState === 'error' && (
        <div>
          <p>Error: {error}</p>
          <button onClick={reconnect}>Reconnect</button>
        </div>
      )}
    </div>
  );
}
```

### Message List

```typescript
function MessageList() {
  const { messages, loading } = useMessageSession();
  
  if (loading) return <Spinner />;
  
  return (
    <div>
      {messages.map(msg => (
        <div key={msg.id}>
          <strong>[{msg.role}]</strong> {msg.content}
          <span>Status: {msg.status}</span>
        </div>
      ))}
    </div>
  );
}
```

## Event Flow

```
1. User sends message
   ↓
2. MessageSessionProvider.sendMessage()
   ↓
3. Optimistic update (add temp message)
   ↓
4. API call: POST /api/v2/sessions/{id}/messages
   ↓
5. PostgreSQL: INSERT message (status=PENDING)
   ↓
6. PostgreSQL NOTIFY → SSE: message_update
   ↓
7. V2SessionProvider receives event
   ↓
8. MessageSessionProvider updates message status
   ↓
9. Celery worker processes message
   ↓
10. Worker publishes EventBus events (agent_status)
    ↓
11. SSE streams agent_status events
    ↓
12. useAgentStatus hook updates
    ↓
13. Worker completes, updates message (status=COMPLETED)
    ↓
14. PostgreSQL NOTIFY → SSE: message_update
    ↓
15. MessageSessionProvider updates final status
```

## Architecture

```
┌─────────────────────────────────────────┐
│          NotebookPage                    │
│  ┌───────────────────────────────────┐  │
│  │    V2SessionProvider (SSE)        │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  MessageSessionProvider     │  │  │
│  │  │  ┌───────────────────────┐  │  │  │
│  │  │  │   NotebookUI          │  │  │  │
│  │  │  │   - MessageList       │  │  │  │
│  │  │  │   - ProgressBar       │  │  │  │
│  │  │  │   - InputBox          │  │  │  │
│  │  │  └───────────────────────┘  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘

SSE Events ──────────────────────┐
  - connected                     │
  - agent_status (transient)      ├─→ V2SessionProvider
  - message_update (persistent)   │
  - ping (keepalive)             ─┘

API Calls ────────────────────────┐
  - sendMessage()                  │
  - getMessages()                  ├─→ MessageSessionProvider
  - refreshMessages()             ─┘
```

## Error Handling

**SSE Errors**:
- Auto-reconnect up to `maxRetries` (default: 5)
- Exponential backoff (2s, 4s, 8s, 16s, 32s)
- Manual reconnect via `reconnect()`

**API Errors**:
- Optimistic updates rolled back on failure
- Error exposed via `error` state
- User can retry manually

**Message Send Errors**:
- Temporary message removed
- Error thrown (can be caught and displayed)

## Testing

```typescript
// Mock SSE connection
const mockContext = {
  connectionState: 'connected',
  lastAgentStatus: { type: 'sql_validating' },
  lastMessageUpdate: { message_id: '123', status: 'completed' },
  reconnect: jest.fn(),
  disconnect: jest.fn(),
};

// Wrap component with provider
<V2SessionProvider sessionId="test-123">
  <YourComponent />
</V2SessionProvider>
```

## Related Docs

- API Client: `app/lib/v2/README.md`
- Architecture: `docs/architecture/v2/v2-frontend-architecture.md`
- Migration: `docs/architecture/v2/v2-migration-strategy.md`
