"use client";

/**
 * NotebookContainer
 *
 * Main container for the V2 notebook interface.
 * Uses split-pane layout with chat on left and data visualization on right.
 */

import { NotebookDashboard } from "./notebook-dashboard";

interface NotebookContainerProps {
  sessionId: string;
}

export function NotebookContainer({ sessionId }: NotebookContainerProps) {
  return <NotebookDashboard sessionId={sessionId} />;
}
