"use client";

/**
 * Agent Steps Component - Shows intermediate steps during processing
 * Displays MCP tool calls, LLM thinking, validation steps, etc.
 */

import {
  Box,
  Collapse,
  Typography,
  Chip,
  LinearProgress,
  CircularProgress,
} from "@mui/material";
import { useState } from "react";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";

export interface AgentStep {
  id: string;
  type: "mcp_call" | "llm_thinking" | "validation" | "execution";
  label: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  details?: string;
  duration_ms?: number;
  metadata?: Record<string, any>;
}

interface AgentStepsProps {
  steps: AgentStep[];
  isExpanded?: boolean;
}

export function AgentSteps({ steps, isExpanded = false }: AgentStepsProps) {
  const [expanded, setExpanded] = useState(isExpanded);

  const getStepIcon = (step: AgentStep) => {
    if (step.status === "completed") {
      return <CheckCircleIcon fontSize="small" color="success" />;
    }
    if (step.status === "in_progress") {
      return <CircularProgress size={16} />;
    }
    if (step.status === "failed") {
      return <CheckCircleIcon fontSize="small" color="error" />;
    }
    return <AccessTimeIcon fontSize="small" sx={{ opacity: 0.5 }} />;
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case "mcp_call":
        return <DataObjectIcon fontSize="small" />;
      case "llm_thinking":
        return <PsychologyIcon fontSize="small" />;
      case "validation":
        return <VerifiedIcon fontSize="small" />;
      default:
        return null;
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "mcp_call":
        return "primary";
      case "llm_thinking":
        return "secondary";
      case "validation":
        return "info";
      default:
        return "default";
    }
  };

  if (steps.length === 0) return null;

  const completedSteps = steps.filter((s) => s.status === "completed").length;
  const totalSteps = steps.length;
  const progress = (completedSteps / totalSteps) * 100;

  return (
    <Box
      sx={{
        my: 2,
        p: 2,
        borderRadius: 1,
        border: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          mb: expanded ? 2 : 0,
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Typography variant="body2" fontWeight="medium">
            Agent Steps
          </Typography>
          <Chip
            label={`${completedSteps}/${totalSteps}`}
            size="small"
            sx={{ height: 20, fontSize: "0.75rem" }}
          />
        </Box>
        {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
      </Box>

      {/* Progress bar */}
      {!expanded && (
        <LinearProgress
          variant="determinate"
          value={progress}
          sx={{ mt: 1, borderRadius: 1 }}
        />
      )}

      {/* Steps list */}
      <Collapse in={expanded}>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
          {steps.map((step, index) => (
            <Box
              key={step.id}
              sx={{
                display: "flex",
                gap: 2,
                alignItems: "flex-start",
                opacity: step.status === "pending" ? 0.5 : 1,
              }}
            >
              {/* Status icon */}
              <Box sx={{ pt: 0.5 }}>{getStepIcon(step)}</Box>

              {/* Step content */}
              <Box sx={{ flex: 1 }}>
                {/* Label and duration */}
                <Box
                  sx={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 1,
                  }}
                >
                  <Typography variant="body2" fontWeight="medium">
                    {step.label}
                  </Typography>
                  {step.duration_ms && (
                    <Typography variant="caption" sx={{ opacity: 0.6 }}>
                      {step.duration_ms}ms
                    </Typography>
                  )}
                </Box>

                {/* Details */}
                {step.details && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      display: "block",
                      mt: 0.5,
                      fontFamily: "monospace",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {step.details}
                  </Typography>
                )}

                {/* Metadata */}
                {step.metadata && Object.keys(step.metadata).length > 0 && (
                  <Box
                    sx={{
                      mt: 1,
                      p: 1,
                      bgcolor: "action.hover",
                      borderRadius: 1,
                    }}
                  >
                    {Object.entries(step.metadata).map(([key, value]) => (
                      <Typography
                        key={key}
                        variant="caption"
                        sx={{ display: "block", fontFamily: "monospace" }}
                      >
                        {key}: {JSON.stringify(value)}
                      </Typography>
                    ))}
                  </Box>
                )}
              </Box>
            </Box>
          ))}
        </Box>
      </Collapse>
    </Box>
  );
}
