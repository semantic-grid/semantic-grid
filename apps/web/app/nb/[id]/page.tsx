/**
 * V2 Notebook Page
 *
 * Notebook-style interface for V2 message-based API.
 * Features:
 * - Cell-based UI (Jupyter-style)
 * - Real-time updates via SSE
 * - Optimistic updates for immediate feedback
 */

import { V2SessionProvider } from '@/app/contexts/v2/SessionProvider';
import { MessageSessionProvider } from '@/app/contexts/v2/MessageSession';
import { NotebookContainer } from './notebook-container';

interface PageProps {
  params: {
    id: string;
  };
}

export default function NotebookPage({ params }: PageProps) {
  const { id: sessionId } = params;

  return (
    <V2SessionProvider sessionId={sessionId} autoConnect={true}>
      <MessageSessionProvider sessionId={sessionId}>
        <NotebookContainer sessionId={sessionId} />
      </MessageSessionProvider>
    </V2SessionProvider>
  );
}
