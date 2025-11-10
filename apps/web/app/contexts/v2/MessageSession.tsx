"use client";

/**
 * MessageSessionProvider - Message State Manager
 *
 * Manages messages for a v2 session using the V2 API client.
 * Integrates with V2SessionProvider for real-time SSE updates.
 *
 * Usage:
 *   <V2SessionProvider sessionId={sessionId}>
 *     <MessageSessionProvider sessionId={sessionId}>
 *       <YourComponent />
 *     </MessageSessionProvider>
 *   </V2SessionProvider>
 *
 * Then in child components:
 *   const { messages, sendMessage, loading } = useMessageSession();
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import { useUser } from "@auth0/nextjs-auth0/client";
import { useV2Session } from "./SessionProvider";
import {
  getMessages,
  sendMessage as apiSendMessage,
  getV2AuthToken,
  type V2Message,
  type MessageRole,
  type MessageKind,
} from "@/app/lib/v2";

// ============================================================================
// Types
// ============================================================================

interface MessageSessionContextValue {
  // Messages
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

// ============================================================================
// Context
// ============================================================================

const MessageSessionContext = createContext<MessageSessionContextValue | null>(
  null,
);

// ============================================================================
// Provider Component
// ============================================================================

interface MessageSessionProviderProps {
  sessionId: string;
  children: React.ReactNode;
  initialMessages?: V2Message[];
  autoLoad?: boolean;
}

export function MessageSessionProvider({
  sessionId,
  children,
  initialMessages = [],
  autoLoad = true,
}: MessageSessionProviderProps) {
  const { user } = useUser();
  const { lastMessageUpdate } = useV2Session();

  // State
  const [messages, setMessages] = useState<V2Message[]>(initialMessages);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Refresh messages from API
   */
  const refreshMessages = useCallback(async () => {
    try {
      console.log(
        "[MessageSession] Refreshing messages for session:",
        sessionId,
      );
      setLoading(true);
      setError(null);

      const token = await getV2AuthToken(user);
      const response = await getMessages(
        sessionId,
        { limit: 1000, persistent_only: true },
        token,
      );

      console.log(
        "[MessageSession] Fetched messages:",
        response.messages.length,
        response.messages,
      );
      setMessages(response.messages);
    } catch (err) {
      console.error("[MessageSession] Failed to load messages:", err);
      setError(err instanceof Error ? err.message : "Failed to load messages");
    } finally {
      setLoading(false);
    }
  }, [sessionId, user]);

  /**
   * Send a message
   */
  const sendMessage = useCallback(
    async (content: string, kind: MessageKind = "chat") => {
      try {
        const token = await getV2AuthToken(user);

        // Optimistic update - add temporary message
        const tempMessage: V2Message = {
          id: `temp-${Date.now()}`,
          session_id: sessionId,
          role: "user",
          kind,
          content,
          content_type: "text/markdown",
          persistent: true,
          metadata: {},
          status: "pending",
          created_at: new Date().toISOString(),
          parent_id: null,
          error: null,
        };

        setMessages((prev) => [...prev, tempMessage]);

        // Send to API
        const response = await apiSendMessage(
          sessionId,
          {
            role: "user",
            kind,
            content,
            content_type: "text/markdown",
          },
          token,
        );

        // Update temp message with the real message_id from response
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tempMessage.id
              ? { ...m, id: response.message_id, status: response.status }
              : m,
          ),
        );

        // Note: Additional messages (assistant response) will come via SSE
      } catch (err) {
        console.error("[MessageSession] Failed to send message:", err);

        // Remove optimistic message on error
        setMessages((prev) => prev.filter((m) => !m.id?.startsWith("temp-")));

        throw err;
      }
    },
    [sessionId, user],
  );

  /**
   * Handle SSE message updates
   */
  useEffect(() => {
    if (!lastMessageUpdate) return;

    console.log("[MessageSession] Received SSE update:", lastMessageUpdate);

    const { message_id, status, session_id } = lastMessageUpdate;

    // Only process updates for this session
    if (session_id !== sessionId) {
      console.log(
        "[MessageSession] Ignoring update for different session:",
        session_id,
        "vs",
        sessionId,
      );
      return;
    }

    setMessages((prev) => {
      const existing = prev.find((m) => m.id === message_id);

      if (existing) {
        console.log(
          "[MessageSession] Updating existing message:",
          message_id,
          "to status:",
          status,
        );
        // Update existing message status
        return prev.map((m) =>
          m.id === message_id
            ? { ...m, status, updated_at: new Date().toISOString() }
            : m,
        );
      } else {
        console.log(
          "[MessageSession] New message detected, refreshing:",
          message_id,
        );
        // New message - fetch full details
        // We'll do a full refresh to get the complete message
        // (SSE event only has minimal info)
        setTimeout(() => refreshMessages(), 100);
        return prev;
      }
    });
  }, [lastMessageUpdate, sessionId, refreshMessages]);

  /**
   * Load initial messages
   */
  useEffect(() => {
    if (autoLoad && messages.length === 0) {
      refreshMessages();
    }
  }, [sessionId]); // Only load once on mount or session change

  /**
   * Computed values
   */
  const userMessages = messages.filter((m) => m.role === "user");
  const assistantMessages = messages.filter((m) => m.role === "assistant");
  const latestMessage =
    messages.length > 0 ? messages[messages.length - 1] : null;

  // Context value
  const value: MessageSessionContextValue = {
    messages,
    loading,
    error,
    sendMessage,
    refreshMessages,
    userMessages,
    assistantMessages,
    latestMessage,
  };

  return (
    <MessageSessionContext.Provider value={value}>
      {children}
    </MessageSessionContext.Provider>
  );
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Use message session
 *
 * Must be used within MessageSessionProvider
 */
export function useMessageSession() {
  const context = useContext(MessageSessionContext);

  if (!context) {
    throw new Error(
      "useMessageSession must be used within MessageSessionProvider",
    );
  }

  return context;
}
