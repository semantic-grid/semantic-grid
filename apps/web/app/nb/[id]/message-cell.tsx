'use client';

/**
 * MessageCell
 *
 * Displays a single message as a notebook cell.
 * Shows execution order, role badge, content, and status.
 */

import { Box, Paper, Chip, Typography, CircularProgress } from '@mui/material';
import { V2Message } from '@/app/lib/v2/types.gen';
import PersonIcon from '@mui/icons-material/Person';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import AccessTimeIcon from '@mui/icons-material/AccessTime';

interface MessageCellProps {
  message: V2Message;
  executionOrder: number;
}

export function MessageCell({ message, executionOrder }: MessageCellProps) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';

  // Status indicators
  const statusConfig = {
    pending: { icon: <AccessTimeIcon />, color: 'default' as const, label: 'Pending' },
    processing: { icon: <CircularProgress size={16} />, color: 'info' as const, label: 'Processing' },
    completed: { icon: <CheckCircleIcon />, color: 'success' as const, label: 'Completed' },
    failed: { icon: <ErrorIcon />, color: 'error' as const, label: 'Failed' },
    cancelled: { icon: <ErrorIcon />, color: 'warning' as const, label: 'Cancelled' },
  };

  const status = statusConfig[message.status] || statusConfig.pending;

  return (
    <Box
      sx={{
        display: 'flex',
        gap: 2,
        mb: 2,
        alignItems: 'flex-start',
      }}
    >
      {/* Execution Order */}
      <Box
        sx={{
          minWidth: 40,
          pt: 2,
          color: 'text.secondary',
          fontFamily: 'monospace',
          fontSize: '0.875rem',
        }}
      >
        [{executionOrder}]:
      </Box>

      {/* Cell Content */}
      <Paper
        elevation={1}
        sx={{
          flex: 1,
          p: 2,
          bgcolor: isUser ? 'background.paper' : 'action.hover',
        }}
      >
        {/* Cell Header */}
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            mb: 1.5,
          }}
        >
          {/* Role Badge */}
          <Chip
            icon={isUser ? <PersonIcon /> : <SmartToyIcon />}
            label={message.role}
            size="small"
            color={isUser ? 'primary' : 'secondary'}
            sx={{ textTransform: 'capitalize' }}
          />

          {/* Status Badge */}
          <Chip
            icon={status.icon}
            label={status.label}
            size="small"
            color={status.color}
          />
        </Box>

        {/* Cell Content */}
        <Typography
          variant="body1"
          sx={{
            whiteSpace: 'pre-wrap',
            fontFamily: message.content_type?.includes('code') ? 'monospace' : 'inherit',
          }}
        >
          {typeof message.content === 'string'
            ? message.content
            : JSON.stringify(message.content, null, 2)}
        </Typography>

        {/* Error Message */}
        {message.error && (
          <Box
            sx={{
              mt: 2,
              p: 1.5,
              bgcolor: 'error.light',
              color: 'error.contrastText',
              borderRadius: 1,
            }}
          >
            <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
              {message.error}
            </Typography>
          </Box>
        )}

        {/* Metadata */}
        {message.metadata && Object.keys(message.metadata).length > 0 && (
          <Box
            sx={{
              mt: 2,
              pt: 1.5,
              borderTop: 1,
              borderColor: 'divider',
            }}
          >
            <Typography variant="caption" color="text.secondary">
              {new Date(message.created_at).toLocaleString()}
            </Typography>
          </Box>
        )}
      </Paper>
    </Box>
  );
}
