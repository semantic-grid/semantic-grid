"use client";

import {
  Box,
  Button,
  Chip,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";

interface ClarificationPromptProps {
  question: string;
  options?: string[];
  context?: string;
  allowFreeform?: boolean;
  onResponse: (response: string) => void;
  disabled?: boolean;
}

/**
 * ClarificationPrompt displays a question from the agent with optional
 * multiple-choice options. Users can select an option or type a custom response.
 *
 * This is part of the "ask user" pattern for agent-user interaction.
 */
export const ClarificationPrompt = ({
  question,
  options,
  context,
  allowFreeform = true,
  onResponse,
  disabled = false,
}: ClarificationPromptProps) => {
  const [customResponse, setCustomResponse] = useState("");

  const handleOptionClick = (option: string) => {
    if (!disabled) {
      onResponse(option);
    }
  };

  const handleCustomSubmit = () => {
    if (!disabled && customResponse.trim()) {
      onResponse(customResponse.trim());
      setCustomResponse("");
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleCustomSubmit();
    }
  };

  return (
    <Box
      sx={{
        p: 2,
        bgcolor: "action.hover",
        borderRadius: 1,
        my: 1,
        border: "1px solid",
        borderColor: "divider",
      }}
    >
      {/* Context - why we're asking */}
      {context && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ mb: 1, display: "block", fontStyle: "italic" }}
        >
          {context}
        </Typography>
      )}

      {/* The question */}
      <Typography variant="body1" sx={{ mb: 2, fontWeight: 500 }}>
        {question}
      </Typography>

      {/* Multiple choice options */}
      {options && options.length > 0 && (
        <Stack
          direction="row"
          spacing={1}
          sx={{ mb: 2, flexWrap: "wrap", gap: 1 }}
        >
          {options.map((option) => (
            <Chip
              key={option}
              label={option}
              onClick={() => handleOptionClick(option)}
              clickable={!disabled}
              color="primary"
              variant="outlined"
              sx={{
                cursor: disabled ? "default" : "pointer",
                opacity: disabled ? 0.6 : 1,
              }}
            />
          ))}
        </Stack>
      )}

      {/* Freeform text input */}
      {allowFreeform && (
        <Stack direction="row" spacing={1}>
          <TextField
            size="small"
            fullWidth
            placeholder={
              options && options.length > 0
                ? "Or type your own response..."
                : "Type your response..."
            }
            value={customResponse}
            onChange={(e) => setCustomResponse(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={disabled}
            sx={{
              "& .MuiOutlinedInput-root": {
                bgcolor: "background.paper",
              },
            }}
          />
          <Button
            variant="contained"
            onClick={handleCustomSubmit}
            disabled={disabled || !customResponse.trim()}
            sx={{ minWidth: 80 }}
          >
            Send
          </Button>
        </Stack>
      )}
    </Box>
  );
};

export default ClarificationPrompt;
