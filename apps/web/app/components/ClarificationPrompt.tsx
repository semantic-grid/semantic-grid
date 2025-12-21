"use client";

import { Box, Button, Stack, Typography } from "@mui/material";

interface ClarificationPromptProps {
  question: string;
  options?: string[];
  context?: string;
  onResponse: (response: string) => void;
  disabled?: boolean;
}

/**
 * ClarificationPrompt displays a clarifying question from the agent.
 * Options are shown as text buttons matching the QueryPlanCard style.
 * Users can click an option or type a response in the main input.
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
    <Box sx={{ my: 1 }}>
      {/* Context - why we're asking */}
      {context && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {context}
        </Typography>
      )}

      {/* The question */}
      <Typography variant="body2" sx={{ mb: 2 }}>
        {question}
      </Typography>

      {/* Multiple choice options - styled like QueryPlanCard buttons */}
      {options && options.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
          {options.map((option) => (
            <Button
              key={option}
              variant="outlined"
              size="small"
              onClick={() => handleOptionClick(option)}
              disabled={disabled}
              sx={{ textTransform: "none" }}
            >
              {option}
            </Button>
          ))}
        </Stack>
      )}
    </Box>
  );
};

export default ClarificationPrompt;
