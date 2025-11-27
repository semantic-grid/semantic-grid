import {
  Notifications,
  PlayArrow,
  Refresh,
  Warning,
} from "@mui/icons-material";
import { Alert, Box, Button, Typography } from "@mui/material";

interface FetchDataOverlayProps {
  onFetch: (withNotification?: boolean) => void;
  isStale?: boolean;
  showNotifyOption?: boolean;
  estimatedRows?: number;
  estimatedSizeGb?: number;
}

export const FetchDataOverlay = ({
  onFetch,
  isStale = false,
  showNotifyOption = false,
  estimatedRows,
  estimatedSizeGb,
}: FetchDataOverlayProps) => (
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
    <Typography variant="body1" color="textSecondary" sx={{ mb: 1 }}>
      {isStale ? "Data may be outdated" : "Ready to load data"}
    </Typography>

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
        onClick={() => onFetch(false)}
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
          onClick={() => onFetch(true)}
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
