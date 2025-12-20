"use client";

import { Box, Chip, Stack, Typography } from "@mui/material";

interface ClarificationPromptProps {
  question: string;
  options?: string[];
  context?: string;
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
  onResponse,
  disabled = false,
}: ClarificationPromptProps) => {
  const handleOptionClick = (option: string) => {
    if (!disabled) {
      onResponse(option);
    }
  };

  return (
    <Box
      sx={{
        my: 1,
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
    </Box>
  );
};

export default ClarificationPrompt;
