'use client';

/**
 * AgentStatusIndicator
 *
 * Shows current agent processing status with progress.
 * Displays at the top of the notebook when agent is working.
 */

import { Box, LinearProgress, Typography, Paper } from '@mui/material';
import { AgentStatus } from '@/app/contexts/v2/useAgentStatus';

interface AgentStatusIndicatorProps {
  status: AgentStatus;
}

export function AgentStatusIndicator({ status }: AgentStatusIndicatorProps) {
  if (!status.isProcessing) return null;

  return (
    <Paper
      elevation={3}
      sx={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        p: 2,
        bgcolor: 'primary.light',
        color: 'primary.contrastText',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 'medium' }}>
            {status.stepLabel}
          </Typography>
          {status.metadata && (
            <Typography variant="caption" sx={{ opacity: 0.8 }}>
              {JSON.stringify(status.metadata)}
            </Typography>
          )}
        </Box>
        {status.progress !== null && (
          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
            {Math.round(status.progress)}%
          </Typography>
        )}
      </Box>
      {status.progress !== null ? (
        <LinearProgress
          variant="determinate"
          value={status.progress}
          sx={{ mt: 1, bgcolor: 'primary.dark' }}
        />
      ) : (
        <LinearProgress sx={{ mt: 1, bgcolor: 'primary.dark' }} />
      )}
    </Paper>
  );
}
