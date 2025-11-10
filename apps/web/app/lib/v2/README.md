# V2 API Client Library

Type-safe API client for Semantic Grid V2 (message-based architecture).

## Overview

This library provides a clean interface to the V2 backend API, which uses a message-based architecture instead of the legacy request/response model.

## Files

- `types.gen.ts` - Auto-generated TypeScript types from OpenAPI spec (DO NOT EDIT)
- `api.ts` - API client functions (sessions, messages)
- `auth.ts` - Authentication helpers (Auth0 + guest tokens)
- `index.ts` - Public exports

## Quick Start

```typescript
import { createV2Session, sendMessage, getMessages } from '@/app/lib/v2';
import { getV2AuthToken } from '@/app/lib/v2';
import { useUser } from '@auth0/nextjs-auth0/client';

// In a React component
const { user } = useUser();
const token = await getV2AuthToken(user);

// Create session
const session = await createV2Session(
  { name: 'My Analysis' },
  token
);

// Send message
const response = await sendMessage(
  session.session_id,
  {
    role: 'user',
    kind: 'interactive_query',
    content: 'Show me top 10 transactions',
  },
  token
);

// Get messages
const messages = await getMessages(
  session.session_id,
  { limit: 50, persistent_only: true },
  token
);
```

## API Functions

### Session Management

**`createV2Session(req, token)`**
- Create a new v2 session
- Returns: `V2Session` with session_id and initial messages

**`getV2Session(sessionId, token)`**
- Get session with all messages
- Returns: `GetSessionResponse` with messages array

### Message Management

**`sendMessage(sessionId, message, token)`**
- Send a message to a session
- Triggers backend processing (creates assistant response)
- Returns: `SendMessageResponse` with created message

**`getMessages(sessionId, options, token)`**
- Get messages for a session
- Options: limit, offset, role, kind, persistent_only
- Returns: `GetMessagesResponse` with messages array

**`getMessage(messageId, token)`**
- Get a single message by ID
- Returns: `V2Message`

### Utilities

**`healthCheck()`**
- Check if v2 API is healthy
- Returns: `boolean`

**`getV2AuthToken(user?)`**
- Get auth token (Auth0 or guest)
- Returns: `Promise<string>`

## Types

Key types exported:

```typescript
// Session
type V2Session = {
  session_id: string;
  api_version: string;
  created_at: string;
  messages: V2Message[];
};

// Message
type V2Message = {
  id: string;
  session_id: string;
  role: MessageRole;      // 'user' | 'assistant' | 'system' | 'tool'
  kind: MessageKind;      // 'chat' | 'interactive_query' | 'table' | etc.
  content: string;
  metadata: Record<string, any>;
  status: MessageStatus;  // 'pending' | 'processing' | 'completed' | 'failed'
  created_at: string;
  updated_at: string;
};

// SSE Events (for real-time updates)
type SSEEvent = 
  | SSEConnectedEvent
  | SSEAgentStatusEvent
  | SSEMessageUpdateEvent
  | SSEPingEvent;
```

## SSE (Server-Sent Events)

For real-time updates, use the SSE stream endpoint:

```typescript
const eventSource = new EventSource(
  `/api/v2/sessions/${sessionId}/stream?token=${encodeURIComponent(token)}`
);

// Connection established
eventSource.addEventListener('connected', (e) => {
  const data = JSON.parse(e.data);
  console.log('Connected:', data.mode); // "hybrid"
});

// Agent progress (transient)
eventSource.addEventListener('agent_status', (e) => {
  const data = JSON.parse(e.data);
  console.log('Status:', data.type); // "llm_thinking", "sql_validating", etc.
});

// Message updates (persistent)
eventSource.addEventListener('message_update', (e) => {
  const data = JSON.parse(e.data);
  console.log('Message:', data.status); // "pending", "processing", "completed"
});

// Cleanup
eventSource.close();
```

See `docs/architecture/v2/v2-frontend-architecture.md` for detailed SSE documentation.

## Regenerating Types

When the backend API changes:

```bash
# Start fm-app locally (with port-forward)
kubectl port-forward -n local svc/fm-app-svc 8080:8080

# Generate types
npm run generate:v2
```

## Testing

**Manual test**:
```bash
npm run test:v2
```

**Integration tests**:
```bash
npm test -- app/lib/v2/__tests__
```

## Migration from V1

| V1 | V2 |
|----|-----|
| `createUserSession()` | `createV2Session()` |
| `createUserRequest()` | `sendMessage()` |
| `getSingleUserRequest()` | `getMessage()` |
| `getAllUserRequestsForSession()` | `getMessages()` |
| Polling every 2s | SSE real-time |
| Request/response model | Message-based |

## Related Docs

- Architecture: `docs/architecture/v2/v2-frontend-architecture.md`
- Migration: `docs/architecture/v2/v2-migration-strategy.md`
- Backend API: `docs/architecture/v2/api-v2-implementation.md`
