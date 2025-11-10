'use client';

/**
 * useAgentStatus Hook
 *
 * Provides current agent processing status with human-readable labels.
 * Uses SSE events from V2SessionProvider.
 *
 * Usage:
 *   const { isProcessing, currentStep, stepLabel, progress } = useAgentStatus();
 */

import { useMemo } from 'react';
import { useV2Session } from './SessionProvider';

// ============================================================================
// Agent Step Labels
// ============================================================================

const AGENT_STEP_LABELS: Record<string, string> = {
  // Lifecycle
  task_received: 'Task received',
  task_started: 'Starting processing',
  task_completed: 'Completed',
  task_failed: 'Failed',

  // Analysis
  intent_analyzing: 'Analyzing your request',
  intent_analyzed: 'Request understood',

  // Planning
  plan_drafting: 'Creating execution plan',
  plan_drafted: 'Plan created',
  plan_step_started: 'Executing plan step',
  plan_step_completed: 'Step completed',

  // Tools
  tool_calling: 'Calling tool',
  tool_called: 'Tool completed',
  tool_failed: 'Tool failed',

  // LLM
  llm_thinking: 'Thinking',
  llm_responded: 'Response generated',

  // SQL Validation
  sql_validating: 'Validating SQL query',
  sql_validated: 'SQL validated',
  sql_invalid: 'SQL invalid',
  sql_repairing: 'Repairing SQL',

  // Execution
  query_executing: 'Running query',
  query_executed: 'Query completed',
  query_failed: 'Query failed',

  // Data
  data_processing: 'Processing results',
  data_processed: 'Results processed',
};

// ============================================================================
// Hook
// ============================================================================

export interface AgentStatus {
  isProcessing: boolean;
  currentStep: string | null;
  stepLabel: string | null;
  progress: number | null;
  metadata: Record<string, any> | null;
}

export function useAgentStatus(): AgentStatus {
  const { lastAgentStatus } = useV2Session();

  return useMemo(() => {
    if (!lastAgentStatus) {
      return {
        isProcessing: false,
        currentStep: null,
        stepLabel: null,
        progress: null,
        metadata: null,
      };
    }

    const { type, progress, metadata } = lastAgentStatus;

    return {
      isProcessing: true,
      currentStep: type,
      stepLabel: AGENT_STEP_LABELS[type] || type,
      progress: progress ?? null,
      metadata: metadata ?? null,
    };
  }, [lastAgentStatus]);
}
