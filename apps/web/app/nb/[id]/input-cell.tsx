'use client';

/**
 * InputCell
 *
 * Input cell for entering queries/messages.
 * Similar to Jupyter notebook input cell.
 */

import { useState } from 'react';
import { Box, TextField, IconButton, Paper } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';

interface InputCellProps {
  onSend: (content: string) => Promise<void>;
  disabled?: boolean;
}

export function InputCell({ onSend, disabled }: InputCellProps) {
  const [value, setValue] = useState('');
  const [isSending, setIsSending] = useState(false);

  const handleSend = async () => {
    if (!value.trim() || isSending || disabled) return;

    setIsSending(true);
    try {
      await onSend(value.trim());
      setValue(''); // Clear input after successful send
    } catch (error) {
      console.error('Failed to send message:', error);
      // Keep the value in case user wants to retry
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Send on Cmd/Ctrl + Enter
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Paper
      elevation={2}
      sx={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: 1,
        p: 1,
      }}
    >
      <TextField
        multiline
        fullWidth
        minRows={1}
        maxRows={10}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type your query here... (⌘+Enter to send)"
        disabled={disabled || isSending}
        variant="outlined"
        sx={{
          '& .MuiOutlinedInput-root': {
            bgcolor: 'background.paper',
          },
        }}
      />
      <IconButton
        color="primary"
        onClick={handleSend}
        disabled={!value.trim() || disabled || isSending}
        size="large"
      >
        <SendIcon />
      </IconButton>
    </Paper>
  );
}
