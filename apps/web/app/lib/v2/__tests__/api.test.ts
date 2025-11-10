/**
 * V2 API Client Tests
 *
 * Basic integration tests for v2 API client.
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from '@jest/globals';
import {
  createV2Session,
  getV2Session,
  sendMessage,
  getMessages,
  healthCheck,
} from '../api';

// Test configuration
const TEST_TOKEN = process.env.TEST_AUTH_TOKEN || 'test-token';
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

describe('V2 API Client', () => {
  beforeAll(() => {
    console.log(`Testing against: ${API_URL}`);
  });

  describe('Health Check', () => {
    it('should return healthy status', async () => {
      const isHealthy = await healthCheck();
      expect(isHealthy).toBe(true);
    });
  });

  describe('Session Management', () => {
    let sessionId: string;

    it('should create a new session', async () => {
      const session = await createV2Session(
        {
          name: 'Test Session',
          tags: 'test,automated',
        },
        TEST_TOKEN
      );

      expect(session).toBeDefined();
      expect(session.session_id).toBeDefined();
      expect(session.api_version).toBe('v2');
      expect(session.messages).toBeInstanceOf(Array);

      sessionId = session.session_id;
    });

    it('should get an existing session', async () => {
      const session = await getV2Session(sessionId, TEST_TOKEN);

      expect(session).toBeDefined();
      expect(session.session_id).toBe(sessionId);
      expect(session.messages).toBeInstanceOf(Array);
    });
  });

  describe('Message Management', () => {
    let sessionId: string;

    beforeAll(async () => {
      const session = await createV2Session({ name: 'Message Test' }, TEST_TOKEN);
      sessionId = session.session_id;
    });

    it('should send a message', async () => {
      const response = await sendMessage(
        sessionId,
        {
          role: 'user',
          kind: 'interactive_query',
          content: 'Show me the top 10 transactions',
        },
        TEST_TOKEN
      );

      expect(response).toBeDefined();
      expect(response.message).toBeDefined();
      expect(response.message.role).toBe('user');
      expect(response.message.kind).toBe('interactive_query');
    });

    it('should get messages for a session', async () => {
      const response = await getMessages(
        sessionId,
        { limit: 10, persistent_only: true },
        TEST_TOKEN
      );

      expect(response).toBeDefined();
      expect(response.messages).toBeInstanceOf(Array);
      expect(response.total_count).toBeGreaterThan(0);
    });

    it('should filter messages by role', async () => {
      const response = await getMessages(
        sessionId,
        { role: 'user' },
        TEST_TOKEN
      );

      expect(response).toBeDefined();
      expect(response.messages.every(m => m.role === 'user')).toBe(true);
    });

    it('should filter messages by kind', async () => {
      const response = await getMessages(
        sessionId,
        { kind: 'interactive_query' },
        TEST_TOKEN
      );

      expect(response).toBeDefined();
      expect(response.messages.every(m => m.kind === 'interactive_query')).toBe(true);
    });
  });
});
