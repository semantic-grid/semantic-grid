"use client";

import { Error,NotificationsActive, Refresh } from "@mui/icons-material";
import { Box, Button, CircularProgress, Typography } from "@mui/material";
import React from "react";

interface FetchOverlayProps {
  onFetch: () => void;
  onFetchWithNotify?: () => void;
  showNotifyOption?: boolean;
  estimatedRows?: number;
  estimatedSizeGb?: number;
  isStale?: boolean;
}

export const FetchOverlay = ({
  onFetch,
  onFetchWithNotify,
  showNotifyOption = false,
  estimatedRows,
  estimatedSizeGb,
  isStale = false,
}: FetchOverlayProps) => {
  const hasWarning = estimatedRows || estimatedSizeGb;

  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      gap={2}
      p={3}
    >
      {hasWarning && (
        <Typography variant="body2" color="warning.main" textAlign="center">
          {estimatedRows && `~${estimatedRows.toLocaleString()} rows`}
          {estimatedRows && estimatedSizeGb && " / "}
          {estimatedSizeGb && `~${estimatedSizeGb.toFixed(2)} GB`}
        </Typography>
      )}

      <Box display="flex" gap={1}>
        <Button
          variant="contained"
          size="small"
          startIcon={<Refresh />}
          onClick={onFetch}
        >
          {isStale ? "Refresh" : "Fetch Data"}
        </Button>

        {showNotifyOption && onFetchWithNotify && (
          <Button
            variant="outlined"
            size="small"
            startIcon={<NotificationsActive />}
            onClick={onFetchWithNotify}
          >
            {isStale ? "Refresh & Notify" : "Fetch & Notify"}
          </Button>
        )}
      </Box>
    </Box>
  );
};

export const LoadingOverlay = () => (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      gap={2}
      p={3}
    >
      <CircularProgress size={32} />
      <Typography variant="body2" color="text.secondary">
        Loading chart data...
      </Typography>
    </Box>
  );

interface ErrorOverlayProps {
  error: string;
  onRetry: () => void;
}

export const ErrorOverlay = ({ error, onRetry }: ErrorOverlayProps) => (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      gap={2}
      p={3}
    >
      <Error color="error" sx={{ fontSize: 32 }} />
      <Typography variant="body2" color="error" textAlign="center">
        {error}
      </Typography>
      <Button variant="outlined" size="small" onClick={onRetry}>
        Retry
      </Button>
    </Box>
  );
