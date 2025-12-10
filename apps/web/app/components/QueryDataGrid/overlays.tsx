"use client";

import {
  Cancel,
  Notifications,
  PlayArrow,
  Refresh,
  Warning,
} from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Typography,
} from "@mui/material";

interface FetchOverlayProps {
  onFetch: () => void;
  onFetchWithNotify: () => void;
  showNotifyOption: boolean;
  estimatedRows?: number;
  estimatedSizeGb?: number;
  isStale?: boolean;
}

export const FetchOverlay = ({
  onFetch,
  onFetchWithNotify,
  showNotifyOption,
  estimatedRows,
  estimatedSizeGb,
  isStale = false,
}: FetchOverlayProps) => (
  <Box
    sx={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      alignItems: "center",
      justifyContent: "center",
      gap: 2,
      px: 3,
    }}
  >
    {showNotifyOption && (estimatedRows || estimatedSizeGb) && (
      <Alert
        severity="warning"
        icon={<Warning />}
        sx={{
          maxWidth: 600,
          mb: 1,
        }}
      >
        <Typography variant="body2" sx={{ fontSize: "0.875rem" }}>
          This query will process{" "}
          {estimatedRows
            ? `${estimatedRows.toLocaleString()} rows`
            : "a large dataset"}
          {estimatedSizeGb ? ` (~${estimatedSizeGb.toFixed(2)} GB)` : ""} and
          may take several minutes.
        </Typography>
        <Typography
          variant="body2"
          sx={{ fontSize: "0.75rem", mt: 0.5, opacity: 0.8 }}
        >
          Consider using &quot;Fetch & Notify Me&quot; to receive an email when
          complete.
        </Typography>
      </Alert>
    )}

    <Box sx={{ display: "flex", gap: 2 }}>
      <Button
        variant="contained"
        size="medium"
        startIcon={isStale ? <Refresh /> : <PlayArrow />}
        onClick={onFetch}
        sx={{
          textTransform: "none",
        }}
      >
        {isStale ? "Refresh Data" : "Fetch Data"}
      </Button>
      {showNotifyOption && (
        <Button
          variant="outlined"
          size="medium"
          startIcon={<Notifications />}
          onClick={onFetchWithNotify}
          sx={{
            textTransform: "none",
          }}
        >
          Fetch & Notify Me
        </Button>
      )}
    </Box>
  </Box>
);

interface LoadingOverlayProps {
  onCancel: () => void;
  showCancel?: boolean;
  message?: string;
}

export const LoadingOverlay = ({
  onCancel,
  showCancel = true,
  message = "Loading data...",
}: LoadingOverlayProps) => (
  <Box
    sx={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      height: "100%",
      gap: 2,
    }}
  >
    <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
      <CircularProgress size={24} />
      <Typography variant="body2" color="text.secondary">
        {message}
      </Typography>
    </Box>
    {showCancel && (
      <Button
        variant="outlined"
        size="small"
        startIcon={<Cancel />}
        onClick={onCancel}
        sx={{ textTransform: "none" }}
      >
        Cancel
      </Button>
    )}
  </Box>
);

interface SpinnerOverlayProps {
  onCancel?: () => void;
}

export const SpinnerOverlay = ({ onCancel }: SpinnerOverlayProps) => (
  <Box
    display="flex"
    flexDirection="column"
    alignItems="center"
    justifyContent="center"
    height="100%"
    gap={2}
  >
    <CircularProgress variant="indeterminate" />
    {onCancel && (
      <Button
        variant="outlined"
        size="small"
        startIcon={<Cancel />}
        onClick={onCancel}
        sx={{ textTransform: "none" }}
      >
        Cancel
      </Button>
    )}
  </Box>
);

interface ErrorOverlayProps {
  error: string;
  onRetry: () => void;
}

export const ErrorOverlay = ({ error, onRetry }: ErrorOverlayProps) => (
  <Box
    sx={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      alignItems: "center",
      justifyContent: "center",
      gap: 2,
      px: 3,
    }}
  >
    <Alert severity="error" sx={{ maxWidth: 600 }}>
      <Typography variant="body2">{error}</Typography>
    </Alert>
    <Button
      variant="outlined"
      size="medium"
      startIcon={<Refresh />}
      onClick={onRetry}
      sx={{ textTransform: "none" }}
    >
      Retry
    </Button>
  </Box>
);

export const NoDataOverlay = () => (
  <Box
    sx={{
      display: "flex",
      height: "100%",
      alignItems: "center",
      justifyContent: "center",
    }}
  >
    <Typography variant="body2" color="textSecondary">
      No results found
    </Typography>
  </Box>
);

interface NotifyPendingOverlayProps {
  onCancel?: () => void;
  compact?: boolean;
}

export const NotifyPendingOverlay = ({
  onCancel,
  compact = false,
}: NotifyPendingOverlayProps) => {
  if (compact) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
        }}
      >
        <Typography variant="body2" color="text.secondary">
          Data fetch request sent.
        </Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        gap: 1,
        px: 3,
      }}
    >
      <Notifications sx={{ fontSize: 24, color: "text.secondary", mb: 0.5 }} />
      <Typography variant="body2" color="text.secondary">
        Data fetch request sent.
      </Typography>
      <Typography variant="body2" color="text.secondary">
        You&apos;ll receive an email once it completes.
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontStyle: "italic" }}
      >
        It&apos;s safe to close the tab now.
      </Typography>
      {onCancel && (
        <Button
          variant="outlined"
          size="small"
          startIcon={<Cancel />}
          onClick={onCancel}
          sx={{ textTransform: "none", mt: 1 }}
        >
          Cancel
        </Button>
      )}
    </Box>
  );
};
