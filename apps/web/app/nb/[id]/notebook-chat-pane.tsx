"use client";

/**
 * NotebookChatPane
 *
 * The chat/notebook section that appears in the left pane.
 * Contains message cells with styled messages and agent steps.
 */

import { Box, Paper, CircularProgress, Alert } from "@mui/material";
import { useMessageSession } from "@/app/contexts/v2/MessageSession";
import { useAgentStatus } from "@/app/contexts/v2/useAgentStatus";
import { StyledMessage } from "../demo/styled-message";
import { AgentSteps } from "../demo/agent-steps";
import { InputCell } from "./input-cell";
import { AgentStatusIndicator } from "./agent-status-indicator";

interface NotebookChatPaneProps {
  sessionId: string;
}

export function NotebookChatPane({ sessionId }: NotebookChatPaneProps) {
  const { messages, loading, error, sendMessage } = useMessageSession();
  const agentStatus = useAgentStatus();

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">Failed to load session: {error}</Alert>
      </Box>
    );
  }

  if (loading && messages.length === 0) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", p: 5 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        minHeight: "calc(100vh - 64px)",
      }}
    >
      {/* Agent Status Indicator */}
      {agentStatus.isProcessing && (
        <AgentStatusIndicator status={agentStatus} />
      )}

      {/* Notebook Messages */}
      <Box
        sx={{
          flex: 1,
          py: 3,
          overflow: "auto",
        }}
      >
        {messages.length === 0 ? (
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "50vh",
            }}
          >
            <Paper
              sx={{
                p: 4,
                textAlign: "center",
                color: "text.secondary",
              }}
            >
              Start by typing a query below...
            </Paper>
          </Box>
        ) : (
          messages.map((message, index) => (
            <Box key={message.id}>
              <StyledMessage message={message} executionOrder={index + 1} />

              {/* Show agent steps for assistant messages that are processing */}
              {message.role === "assistant" &&
                message.status === "processing" &&
                agentStatus.steps.length > 0 && (
                  <AgentSteps steps={agentStatus.steps} isExpanded={false} />
                )}
            </Box>
          ))
        )}
      </Box>

      {/* Input Cell (sticky at bottom) */}
      <Box
        sx={{
          position: "sticky",
          bottom: 0,
          borderTop: 1,
          borderColor: "divider",
          bgcolor: "background.paper",
          p: 2,
          mt: 2,
        }}
      >
        <InputCell onSend={sendMessage} disabled={agentStatus.isProcessing} />
      </Box>
    </Box>
  );
}
