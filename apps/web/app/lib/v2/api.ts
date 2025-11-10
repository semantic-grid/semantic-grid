/**
 * V2 API Client
 *
 * Message-based API for Semantic Grid notebook interface.
 * Uses openapi-fetch for type-safe API calls.
 */

import createClient from "openapi-fetch";
import type { paths, components } from "./types.gen";

// Type aliases for convenience
export type V2Session = components["schemas"]["CreateSessionResponse"];
export type V2Message = components["schemas"]["Message"];
export type MessageRole = components["schemas"]["MessageRole"];
export type MessageKind = components["schemas"]["MessageKind"];
export type MessageStatus = components["schemas"]["MessageStatus"];
export type CreateSessionRequest =
  components["schemas"]["CreateSessionRequest"];
export type SendMessageRequest = components["schemas"]["SendMessageRequest"];
export type GetMessagesResponse = components["schemas"]["GetMessagesResponse"];

// Create client instance
const client = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080",
});

/**
 * Set authorization token for all requests
 */
export function setAuthToken(token: string) {
  client.use({
    onRequest({ request }) {
      request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  });
}

// ============================================================================
// Session Management
// ============================================================================

/**
 * Create a new v2 session
 */
export async function createV2Session(
  req: CreateSessionRequest,
  token: string,
): Promise<V2Session> {
  const { data, error } = await client.POST("/api/v2/sessions", {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: req,
  });

  if (error) {
    throw new Error(error.detail || "Failed to create session");
  }

  return data;
}

/**
 * Get a v2 session with all messages
 */
export async function getV2Session(
  sessionId: string,
  token: string,
): Promise<components["schemas"]["GetSessionResponse"]> {
  const { data, error } = await client.GET("/api/v2/sessions/{session_id}", {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    params: {
      path: { session_id: sessionId },
    },
  });

  if (error) {
    throw new Error(error.detail || "Failed to get session");
  }

  return data;
}

// ============================================================================
// Message Management
// ============================================================================

/**
 * Send a message to a session
 */
export async function sendMessage(
  sessionId: string,
  message: SendMessageRequest,
  token: string,
): Promise<components["schemas"]["SendMessageResponse"]> {
  const { data, error } = await client.POST(
    "/api/v2/sessions/{session_id}/messages",
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
      params: {
        path: { session_id: sessionId },
      },
      body: message,
    },
  );

  if (error) {
    throw new Error(error.detail || "Failed to send message");
  }

  return data;
}

/**
 * Get messages for a session with optional filtering
 */
export async function getMessages(
  sessionId: string,
  options: {
    limit?: number;
    offset?: number;
    role?: MessageRole;
    kind?: MessageKind;
    persistent_only?: boolean;
  } = {},
  token: string,
): Promise<GetMessagesResponse> {
  const { data, error } = await client.GET(
    "/api/v2/sessions/{session_id}/messages",
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
      params: {
        path: { session_id: sessionId },
        query: {
          limit: options.limit,
          offset: options.offset,
          role: options.role,
          kind: options.kind,
          persistent_only: options.persistent_only,
        },
      },
    },
  );

  if (error) {
    throw new Error(error.detail || "Failed to get messages");
  }

  return data;
}

/**
 * Get a single message by ID
 */
export async function getMessage(
  messageId: string,
  token: string,
): Promise<V2Message> {
  const { data, error } = await client.GET("/api/v2/messages/{message_id}", {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    params: {
      path: { message_id: messageId },
    },
  });

  if (error) {
    throw new Error(error.detail || "Failed to get message");
  }

  return data;
}

// ============================================================================
// Health Check
// ============================================================================

/**
 * Health check endpoint
 */
export async function healthCheck(): Promise<boolean> {
  try {
    const { error } = await client.GET("/api/v2/health");
    return !error;
  } catch {
    return false;
  }
}

// ============================================================================
// Helper Types for Frontend
// ============================================================================

/**
 * SSE Event types from the stream endpoint
 */
export type SSEEventType =
  | "connected"
  | "agent_status"
  | "message_update"
  | "ping";

export interface SSEConnectedEvent {
  event: "connected";
  data: {
    session_id: string;
    mode: "hybrid";
  };
}

export interface SSEAgentStatusEvent {
  event: "agent_status";
  data: {
    type: string; // AgentEventType
    message_id: string;
    step?: string;
    progress?: number;
    metadata?: Record<string, any>;
  };
}

export interface SSEMessageUpdateEvent {
  event: "message_update";
  data: {
    message_id: string;
    session_id: string;
    role: MessageRole;
    kind: MessageKind;
    status: MessageStatus;
    has_error: boolean;
    created_at: number;
    operation: "INSERT" | "UPDATE";
  };
}

export interface SSEPingEvent {
  event: "ping";
  data: {
    timestamp: string;
  };
}

export type SSEEvent =
  | SSEConnectedEvent
  | SSEAgentStatusEvent
  | SSEMessageUpdateEvent
  | SSEPingEvent;
