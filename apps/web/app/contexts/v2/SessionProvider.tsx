"use client";

/**
 * V2SessionProvider - SSE Connection Manager
 *
 * Manages Server-Sent Events (SSE) connection for real-time updates.
 * Handles hybrid SSE (EventBus + PostgreSQL NOTIFY).
 *
 * Usage:
 *   <V2SessionProvider sessionId={sessionId}>
 *     <YourComponent />
 *   </V2SessionProvider>
 *
 * Then in child components:
 *   const { connectionState, lastAgentStatus, lastMessageUpdate } = useV2Session();
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
} from "react";
import type { SSEAgentStatusEvent, SSEMessageUpdateEvent } from "@/app/lib/v2";

// ============================================================================
// Types
// ============================================================================

export type ConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "error";

interface V2SessionContextValue {
  // Connection state
  connectionState: ConnectionState;
  error: string | null;

  // Latest events
  lastAgentStatus: SSEAgentStatusEvent["data"] | null;
  lastMessageUpdate: SSEMessageUpdateEvent["data"] | null;

  // Controls
  reconnect: () => void;
  disconnect: () => void;
}

// ============================================================================
// Context
// ============================================================================

const V2SessionContext = createContext<V2SessionContextValue | null>(null);

// ============================================================================
// Provider Component
// ============================================================================

interface V2SessionProviderProps {
  sessionId: string;
  children: React.ReactNode;
  autoConnect?: boolean;
  maxRetries?: number;
  retryDelayMs?: number;
}

export function V2SessionProvider({
  sessionId,
  children,
  autoConnect = true,
  maxRetries = 5,
  retryDelayMs = 2000,
}: V2SessionProviderProps) {
  // State
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [lastAgentStatus, setLastAgentStatus] = useState<
    SSEAgentStatusEvent["data"] | null
  >(null);
  const [lastMessageUpdate, setLastMessageUpdate] = useState<
    SSEMessageUpdateEvent["data"] | null
  >(null);

  // Refs
  const eventSourceRef = useRef<EventSource | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  /**
   * Connect to SSE endpoint
   */
  const connect = useCallback(async () => {
    // Don't connect if already connected or connecting
    if (connectionState === "connected" || connectionState === "connecting") {
      return;
    }

    setConnectionState("connecting");
    setError(null);

    try {
      // Build SSE URL (auth via cookies, like v1)
      const baseUrl =
        process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
      const url = `${baseUrl}/api/v2/sessions/${sessionId}/stream`;

      // Create EventSource with credentials to send cookies
      const eventSource = new EventSource(url, { withCredentials: true });
      eventSourceRef.current = eventSource;

      // Connection opened
      eventSource.addEventListener("open", () => {
        console.log("[V2Session] SSE connection opened");
      });

      // Connected event (hybrid mode confirmation)
      eventSource.addEventListener("connected", (event) => {
        const data = JSON.parse(event.data);
        console.log("[V2Session] Connected:", data);

        if (data.mode === "hybrid") {
          setConnectionState("connected");
          retriesRef.current = 0; // Reset retry counter
        }
      });

      // Agent status events (from EventBus - transient)
      eventSource.addEventListener("agent_status", (event) => {
        const data = JSON.parse(event.data);
        console.log("[V2Session] Agent status:", data.type);
        setLastAgentStatus(data);
      });

      // Message update events (from PostgreSQL NOTIFY - persistent)
      eventSource.addEventListener("message_update", (event) => {
        const data = JSON.parse(event.data);
        console.log("[V2Session] Message update:", data);
        setLastMessageUpdate(data);
      });

      // Ping events (keepalive)
      eventSource.addEventListener("ping", () => {
        // Just keepalive, no action needed
      });

      // Error handling
      eventSource.onerror = (err) => {
        console.error("[V2Session] SSE error:", err);
        setConnectionState("error");
        eventSource.close();
        eventSourceRef.current = null;

        // Auto-reconnect with exponential backoff
        if (retriesRef.current < maxRetries) {
          const delay = retryDelayMs * Math.pow(2, retriesRef.current);
          console.log(
            `[V2Session] Reconnecting in ${delay}ms (attempt ${retriesRef.current + 1}/${maxRetries})`,
          );

          retriesRef.current += 1;

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          setError("Connection failed after multiple retries");
          console.error("[V2Session] Max retries reached");
        }
      };
    } catch (err) {
      console.error("[V2Session] Failed to connect:", err);
      setConnectionState("error");
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }, [sessionId, connectionState, maxRetries, retryDelayMs]);

  /**
   * Disconnect from SSE endpoint
   */
  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      console.log("[V2Session] Disconnecting");
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setConnectionState("disconnected");
    retriesRef.current = 0;
  }, []);

  /**
   * Reconnect (manual)
   */
  const reconnect = useCallback(() => {
    disconnect();
    retriesRef.current = 0; // Reset retry counter
    setTimeout(() => connect(), 100); // Small delay before reconnect
  }, [disconnect, connect]);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    // Cleanup on unmount
    return () => {
      disconnect();
    };
  }, [sessionId]); // Only reconnect if sessionId changes

  // Context value
  const value: V2SessionContextValue = {
    connectionState,
    error,
    lastAgentStatus,
    lastMessageUpdate,
    reconnect,
    disconnect,
  };

  return (
    <V2SessionContext.Provider value={value}>
      {children}
    </V2SessionContext.Provider>
  );
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Use V2 session SSE connection
 *
 * Must be used within V2SessionProvider
 */
export function useV2Session() {
  const context = useContext(V2SessionContext);

  if (!context) {
    throw new Error("useV2Session must be used within V2SessionProvider");
  }

  return context;
}
