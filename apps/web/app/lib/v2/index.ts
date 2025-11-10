/**
 * V2 API Library
 *
 * Export all v2 API functions, types, and utilities.
 */

// API functions
export {
  createV2Session,
  getV2Session,
  sendMessage,
  getMessages,
  getMessage,
  healthCheck,
  setAuthToken,
} from './api';

// Types
export type {
  V2Session,
  V2Message,
  MessageRole,
  MessageKind,
  MessageStatus,
  CreateSessionRequest,
  SendMessageRequest,
  GetMessagesResponse,
  SSEEventType,
  SSEConnectedEvent,
  SSEAgentStatusEvent,
  SSEMessageUpdateEvent,
  SSEPingEvent,
  SSEEvent,
} from './api';

// Auth helpers
export { getV2AuthToken, checkQuota } from './auth';
