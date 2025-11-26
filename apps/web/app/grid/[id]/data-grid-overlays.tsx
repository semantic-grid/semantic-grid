import { PlayArrow, Refresh } from "@mui/icons-material";
import { Box, Button, Typography } from "@mui/material";

interface FetchDataOverlayProps {
  onFetch: () => void;
  isStale?: boolean;
}

export const FetchDataOverlay = ({
  onFetch,
  isStale = false,
}: FetchDataOverlayProps) => (
  <Box
    sx={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      alignItems: "center",
      justifyContent: "center",
      gap: 2,
    }}
  >
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
