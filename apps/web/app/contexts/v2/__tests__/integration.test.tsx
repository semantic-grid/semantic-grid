/**
 * V2 Contexts Integration Tests
 *
 * Tests the integration between V2SessionProvider and MessageSessionProvider.
 */

import { describe, it, expect, jest } from '@jest/globals';
import { render, screen, waitFor } from '@testing-library/react';
import { V2SessionProvider, MessageSessionProvider, useV2Session, useMessageSession } from '../';

// Mock Auth0
jest.mock('@auth0/nextjs-auth0/client', () => ({
  useUser: () => ({ user: null }),
}));

// Mock API client
jest.mock('@/app/lib/v2', () => ({
  getV2AuthToken: jest.fn().mockResolvedValue('mock-token'),
  getMessages: jest.fn().mockResolvedValue({
    messages: [],
    total_count: 0,
    has_more: false,
  }),
  sendMessage: jest.fn().mockResolvedValue({
    message: {
      id: 'msg-123',
      session_id: 'test-session',
      role: 'user',
      kind: 'interactive_query',
      content: 'test message',
      status: 'pending',
      metadata: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  }),
}));

describe('V2 Contexts Integration', () => {
  const TEST_SESSION_ID = 'test-session-123';

  describe('V2SessionProvider', () => {
    it('should provide connection state', () => {
      function TestComponent() {
        const { connectionState } = useV2Session();
        return <div>State: {connectionState}</div>;
      }

      render(
        <V2SessionProvider sessionId={TEST_SESSION_ID} autoConnect={false}>
          <TestComponent />
        </V2SessionProvider>
      );

      expect(screen.getByText(/State:/)).toBeTruthy();
    });

    it('should throw error when used outside provider', () => {
      function TestComponent() {
        useV2Session();
        return null;
      }

      expect(() => render(<TestComponent />)).toThrow(
        'useV2Session must be used within V2SessionProvider'
      );
    });
  });

  describe('MessageSessionProvider', () => {
    it('should provide message state', async () => {
      function TestComponent() {
        const { messages, loading } = useMessageSession();
        return (
          <div>
            <div>Loading: {loading.toString()}</div>
            <div>Messages: {messages.length}</div>
          </div>
        );
      }

      render(
        <V2SessionProvider sessionId={TEST_SESSION_ID} autoConnect={false}>
          <MessageSessionProvider sessionId={TEST_SESSION_ID} autoLoad={false}>
            <TestComponent />
          </MessageSessionProvider>
        </V2SessionProvider>
      );

      expect(screen.getByText(/Messages: 0/)).toBeTruthy();
    });

    it('should throw error when used outside provider', () => {
      function TestComponent() {
        useMessageSession();
        return null;
      }

      expect(() => render(<TestComponent />)).toThrow(
        'useMessageSession must be used within MessageSessionProvider'
      );
    });

    it('should load messages on mount', async () => {
      const { getMessages } = require('@/app/lib/v2');

      function TestComponent() {
        const { messages } = useMessageSession();
        return <div>Count: {messages.length}</div>;
      }

      render(
        <V2SessionProvider sessionId={TEST_SESSION_ID} autoConnect={false}>
          <MessageSessionProvider sessionId={TEST_SESSION_ID}>
            <TestComponent />
          </MessageSessionProvider>
        </V2SessionProvider>
      );

      await waitFor(() => {
        expect(getMessages).toHaveBeenCalled();
      });
    });
  });

  describe('Integration', () => {
    it('should work together', () => {
      function TestComponent() {
        const { connectionState } = useV2Session();
        const { messages } = useMessageSession();

        return (
          <div>
            <div>Connection: {connectionState}</div>
            <div>Messages: {messages.length}</div>
          </div>
        );
      }

      render(
        <V2SessionProvider sessionId={TEST_SESSION_ID} autoConnect={false}>
          <MessageSessionProvider sessionId={TEST_SESSION_ID} autoLoad={false}>
            <TestComponent />
          </MessageSessionProvider>
        </V2SessionProvider>
      );

      expect(screen.getByText(/Connection:/)).toBeTruthy();
      expect(screen.getByText(/Messages:/)).toBeTruthy();
    });
  });
});
