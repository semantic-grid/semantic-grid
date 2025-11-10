"use client";

/**
 * Demo page showing what a V2 notebook session looks like with mock data
 */

import { Box, Container, Paper, Typography } from "@mui/material";
import { StyledMessage } from "./styled-message";
import { AgentSteps } from "./agent-steps";
import { InputCell } from "../[id]/input-cell";
import { AgentStatusIndicator } from "../[id]/agent-status-indicator";
import type { V2Message } from "@/app/lib/v2/types.gen";

// Mock messages showing different states and types
const mockMessages: V2Message[] = [
  {
    id: "1",
    session_id: "demo-session",
    role: "user",
    kind: "chat",
    content: "Show me the top 10 transactions by value from the last 24 hours",
    content_type: "text/markdown",
    status: "completed",
    created_at: "2025-01-09T10:00:00Z",
    updated_at: "2025-01-09T10:00:00Z",
    metadata: {},
    persistent: true,
    parent_id: null,
    thread_id: null,
    tags: [],
    error: null,
  },
  {
    id: "2",
    session_id: "demo-session",
    role: "assistant",
    kind: "chat",
    content:
      "I'll query the transactions table to find the top 10 by value. Let me generate the SQL query...",
    content_type: "text/markdown",
    status: "completed",
    created_at: "2025-01-09T10:00:05Z",
    updated_at: "2025-01-09T10:00:05Z",
    metadata: {},
    persistent: true,
    parent_id: "1",
    thread_id: null,
    tags: [],
    error: null,
  },
  {
    id: "3",
    session_id: "demo-session",
    role: "assistant",
    kind: "query_result",
    content: `SELECT
  transaction_hash,
  from_address,
  to_address,
  value,
  timestamp
FROM transactions
WHERE timestamp >= NOW() - INTERVAL '24 hours'
ORDER BY value DESC
LIMIT 10`,
    content_type: "text/sql",
    status: "completed",
    created_at: "2025-01-09T10:00:10Z",
    updated_at: "2025-01-09T10:00:10Z",
    metadata: {
      execution_time_ms: 145,
      rows_returned: 10,
    },
    persistent: true,
    parent_id: "2",
    thread_id: null,
    tags: ["sql", "query"],
    error: null,
  },
  {
    id: "4",
    session_id: "demo-session",
    role: "user",
    kind: "chat",
    content: "Can you also show me a breakdown by chain?",
    content_type: "text/markdown",
    status: "completed",
    created_at: "2025-01-09T10:01:00Z",
    updated_at: "2025-01-09T10:01:00Z",
    metadata: {},
    persistent: true,
    parent_id: "3",
    thread_id: null,
    tags: [],
    error: null,
  },
  {
    id: "5",
    session_id: "demo-session",
    role: "assistant",
    kind: "chat",
    content: "I'll modify the query to group by blockchain...",
    content_type: "text/markdown",
    status: "processing",
    created_at: "2025-01-09T10:01:05Z",
    updated_at: "2025-01-09T10:01:05Z",
    metadata: {},
    persistent: true,
    parent_id: "4",
    thread_id: null,
    tags: [],
    error: null,
  },
  {
    id: "6",
    session_id: "demo-session",
    role: "user",
    kind: "chat",
    content: "What about failed transactions?",
    content_type: "text/markdown",
    status: "failed",
    created_at: "2025-01-09T10:02:00Z",
    updated_at: "2025-01-09T10:02:00Z",
    metadata: {},
    persistent: true,
    parent_id: null,
    thread_id: null,
    tags: [],
    error: 'Query validation failed: column "status" does not exist',
  },
];

// Mock agent status
const mockAgentStatus = {
  isProcessing: true,
  currentStep: "sql_validating",
  stepLabel: "Validating SQL query",
  progress: 65,
  metadata: {
    query_type: "SELECT",
    estimated_cost: "low",
  },
};

// Mock agent steps for first query (completed)
const mockStepsQuery1 = [
  {
    id: "step-1",
    type: "llm_thinking" as const,
    label: "Analyzing user intent",
    status: "completed" as const,
    details: "Understanding request: top 10 transactions by value in last 24h",
    duration_ms: 450,
  },
  {
    id: "step-2",
    type: "mcp_call" as const,
    label: "Fetching schema from db_meta",
    status: "completed" as const,
    details: "MCP Tool: describe_provider(profile='wh_v2')",
    duration_ms: 120,
    metadata: {
      tables_found: 15,
      relevant_tables: ["transactions", "addresses"],
    },
  },
  {
    id: "step-3",
    type: "llm_thinking" as const,
    label: "Generating SQL query",
    status: "completed" as const,
    duration_ms: 890,
    metadata: {
      model: "claude-sonnet-4",
      tokens: 1250,
    },
  },
  {
    id: "step-4",
    type: "validation" as const,
    label: "Pre-flight validation via db_meta",
    status: "completed" as const,
    details: "MCP Tool: explain_analyze(sql, profile='wh_v2')",
    duration_ms: 340,
    metadata: {
      estimated_rows: 10,
      estimated_cost: "0.05 credits",
    },
  },
  {
    id: "step-5",
    type: "execution" as const,
    label: "Executing query",
    status: "completed" as const,
    duration_ms: 145,
    metadata: {
      rows_returned: 10,
    },
  },
];

// Mock agent steps for second query (in progress)
const mockStepsQuery2 = [
  {
    id: "step-6",
    type: "llm_thinking" as const,
    label: "Understanding follow-up request",
    status: "completed" as const,
    duration_ms: 320,
  },
  {
    id: "step-7",
    type: "mcp_call" as const,
    label: "Fetching schema metadata",
    status: "completed" as const,
    duration_ms: 95,
  },
  {
    id: "step-8",
    type: "llm_thinking" as const,
    label: "Modifying query to group by chain",
    status: "in_progress" as const,
  },
  {
    id: "step-9",
    type: "validation" as const,
    label: "Pre-flight check",
    status: "pending" as const,
  },
];

export default function NotebookDemoPage() {
  return (
    <Box
      sx={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        bgcolor: "background.default",
      }}
    >
      {/* Demo Banner */}
      <Paper
        sx={{
          p: 2,
          bgcolor: "info.main",
          color: "info.contrastText",
          borderRadius: 0,
        }}
      >
        <Typography variant="h6">📝 Notebook Demo - Static Preview</Typography>
        <Typography variant="body2">
          This is a preview of what a V2 notebook session looks like with mock
          data. Visit <strong>/nb</strong> to create a live session.
        </Typography>
      </Paper>

      {/* Agent Status Indicator (showing) */}
      <AgentStatusIndicator status={mockAgentStatus} />

      {/* Notebook Messages - Container matches existing chat UI */}
      <Box
        sx={{
          flex: 1,
          overflow: "auto",
        }}
      >
        <Container maxWidth="lg" sx={{ py: 3 }}>
          {mockMessages.map((message, index) => (
            <Box key={message.id}>
              <StyledMessage message={message} executionOrder={index + 1} />
              {/* Show agent steps after SQL query message (id='3') */}
              {message.id === "3" && (
                <AgentSteps steps={mockStepsQuery1} isExpanded={false} />
              )}
              {/* Show in-progress agent steps after message id='5' */}
              {message.id === "5" && (
                <AgentSteps steps={mockStepsQuery2} isExpanded={true} />
              )}
            </Box>
          ))}
        </Container>
      </Box>

      {/* Input Area (disabled in demo) - matches existing chat input */}
      <Box
        sx={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          background: (theme) => theme.palette.background.paper,
          borderTop: 1,
          borderColor: "divider",
        }}
      >
        <Container maxWidth="lg" sx={{ py: 2 }}>
          <InputCell onSend={async () => {}} disabled={true} />
        </Container>
      </Box>
    </Box>
  );
}
