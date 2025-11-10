import React, { useState } from 'react';
import {
  Box,
  Typography,
  Collapse,
  IconButton,
  LinearProgress,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import CircularProgress from '@mui/material/CircularProgress';

export interface AgentStep {
  id: string;
  type: 'mcp_call' | 'llm_thinking' | 'validation' | 'execution';
  label: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
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

  const completedSteps = steps.filter((s) => s.status === 'completed').length;
  const progress = (completedSteps / steps.length) * 100;

  const getStepIcon = (step: AgentStep) => {
    if (step.status === 'completed') {
      return <CheckCircleIcon fontSize="small" color="success" />;
    }
    if (step.status === 'in_progress') {
      return <CircularProgress size={16} />;
    }
    if (step.status === 'failed') {
      return <CheckCircleIcon fontSize="small" color="error" />;
    }
    return <AccessTimeIcon fontSize="small" sx={{ opacity: 0.5 }} />;
  };

  return (
    <Box sx={{ my: 2, p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ flex: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            Agent Workflow ({completedSteps}/{steps.length} steps)
          </Typography>
          <LinearProgress
            variant="determinate"
            value={progress}
            sx={{ mt: 1, height: 4, borderRadius: 2 }}
          />
        </Box>
        <IconButton size="small">
          {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
        </IconButton>
      </Box>

      <Collapse in={expanded}>
        <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {steps.map((step) => (
            <Box key={step.id} sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
              <Box sx={{ mt: 0.5 }}>{getStepIcon(step)}</Box>

              <Box sx={{ flex: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 500 }}>
                    {step.label}
                  </Typography>
                  {step.duration_ms !== undefined && (
                    <Typography variant="caption" sx={{ opacity: 0.6 }}>
                      {step.duration_ms}ms
                    </Typography>
                  )}
                </Box>

                {step.details && (
                  <Typography variant="caption" sx={{ opacity: 0.7, display: 'block', mt: 0.5 }}>
                    {step.details}
                  </Typography>
                )}

                {step.metadata && Object.keys(step.metadata).length > 0 && (
                  <Box sx={{ mt: 0.5, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {Object.entries(step.metadata).map(([key, value]) => (
                      <Typography key={key} variant="caption" sx={{ opacity: 0.6 }}>
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
