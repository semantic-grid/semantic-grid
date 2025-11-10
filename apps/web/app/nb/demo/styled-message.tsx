"use client";

/**
 * Styled message component matching existing chat UI
 */

import { Box, Chip, Typography } from "@mui/material";
import { useContext } from "react";
import { ThemeContext } from "@/app/contexts/Theme";
import type { V2Message } from "@/app/lib/v2/types.gen";
import PersonIcon from "@mui/icons-material/Person";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import { CircularProgress } from "@mui/material";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface StyledMessageProps {
  message: V2Message;
  executionOrder: number;
}

export function StyledMessage({ message, executionOrder }: StyledMessageProps) {
  const { mode } = useContext(ThemeContext);
  const isUser = message.role === "user";

  // Background color matching existing chat
  const getBgColor = () => {
    if (isUser) return mode === "dark" ? "grey.800" : "#E9e8e6";
    return "unset";
  };

  // Status indicators
  const getStatusIcon = () => {
    switch (message.status) {
      case "pending":
        return <AccessTimeIcon fontSize="small" />;
      case "processing":
        return <CircularProgress size={16} />;
      case "completed":
        return <CheckCircleIcon fontSize="small" />;
      case "failed":
        return <ErrorIcon fontSize="small" />;
      default:
        return null;
    }
  };

  const getStatusColor = () => {
    switch (message.status) {
      case "pending":
        return "default";
      case "processing":
        return "info";
      case "completed":
        return "success";
      case "failed":
        return "error";
      default:
        return "default";
    }
  };

  return (
    <Box sx={{ mb: 2 }}>
      {/* Message bubble - full width */}
      <Box
        sx={{
          display: "flex",
          justifyContent: isUser ? "flex-end" : "flex-start",
        }}
      >
        <Box
          sx={{
            borderRadius: "12px",
            padding: 2,
            bgcolor: getBgColor(),
            width: "100%",
          }}
        >
          {/* Subtle header - role icon + status */}
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              mb: 1,
            }}
          >
            {/* Role icon - subtle */}
            <Box sx={{ display: "flex", alignItems: "center", opacity: 0.6 }}>
              {isUser ? (
                <PersonIcon fontSize="small" />
              ) : (
                <SmartToyIcon fontSize="small" />
              )}
            </Box>

            {/* Status chip - only show if not completed */}
            {message.status !== "completed" && (
              <Chip
                icon={getStatusIcon()}
                label={message.status}
                size="small"
                color={getStatusColor() as any}
                sx={{ height: 24 }}
              />
            )}
          </Box>

          {/* Message content */}
          <Box
            sx={{
              "& p": { margin: 0 },
              "& pre": {
                bgcolor: mode === "dark" ? "grey.900" : "grey.100",
                p: 1,
                borderRadius: 1,
                overflow: "auto",
              },
              "& code": {
                fontFamily: "monospace",
                fontSize: "0.875rem",
              },
            }}
          >
            {typeof message.content === "string" ? (
              message.content_type?.includes("sql") ||
              message.content_type?.includes("code") ? (
                <pre>
                  <code>{message.content}</code>
                </pre>
              ) : (
                <Markdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </Markdown>
              )
            ) : (
              <pre>
                <code>{JSON.stringify(message.content, null, 2)}</code>
              </pre>
            )}
          </Box>

          {/* Error message */}
          {message.error && (
            <Box
              sx={{
                mt: 2,
                p: 1.5,
                bgcolor: "error.dark",
                color: "error.contrastText",
                borderRadius: 1,
              }}
            >
              <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                {message.error}
              </Typography>
            </Box>
          )}

          {/* Metadata */}
          {message.metadata && Object.keys(message.metadata).length > 0 && (
            <Box sx={{ mt: 1.5, pt: 1, borderTop: 1, borderColor: "divider" }}>
              <Typography variant="caption" color="text.secondary">
                {Object.entries(message.metadata)
                  .map(([key, value]) => `${key}: ${value}`)
                  .join(" • ")}
              </Typography>
            </Box>
          )}

          {/* Timestamp */}
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {new Date(message.created_at).toLocaleTimeString()}
            </Typography>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
