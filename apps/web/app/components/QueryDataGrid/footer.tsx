"use client";

import { Cancel, Notifications, Refresh } from "@mui/icons-material";
import { Box, Button, styled, Typography } from "@mui/material";
import {
  GridFooter,
  GridFooterContainer,
  useGridApiContext,
} from "@mui/x-data-grid-pro";

import { pulse } from "@/app/components/dancing-balls";

const PulsingMonoText = styled(Typography)(({ theme }) => ({
  fontFamily: theme.typography.caption.fontFamily,
  animation: `${pulse} 1.5s ease-in-out infinite`,
}));

interface QueryDataGridFooterProps {
  isFetching: boolean;
  isValidating: boolean;
  showNotifyOption: boolean;
  onRefresh: () => void;
  onRefreshWithNotify: () => void;
  onCancel: () => void;
}

export const QueryDataGridFooter = ({
  isFetching,
  isValidating,
  showNotifyOption,
  onRefresh,
  onRefreshWithNotify,
  onCancel,
}: QueryDataGridFooterProps) => {
  const apiRef = useGridApiContext();
  const isFetchingMore = isValidating && !isFetching;

  return (
    <GridFooterContainer
      sx={{
        display: "flex",
        flexDirection: "row",
        justifyContent: "space-between",
        alignItems: "center",
        px: 1,
      }}
    >
      {/* Left side: Loading indicator or action buttons */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        {isFetchingMore && <PulsingMonoText>Loading more...</PulsingMonoText>}

        {!isFetching && !isValidating && (
          <>
            <Button
              variant="text"
              size="small"
              startIcon={<Refresh />}
              onClick={onRefresh}
              sx={{ textTransform: "none" }}
            >
              Refresh
            </Button>
            {showNotifyOption && (
              <Button
                variant="text"
                size="small"
                startIcon={<Notifications />}
                onClick={onRefreshWithNotify}
                sx={{ textTransform: "none" }}
              >
                Refresh & Notify
              </Button>
            )}
          </>
        )}

        {(isFetching || isValidating) && (
          <Button
            variant="text"
            size="small"
            startIcon={<Cancel />}
            onClick={onCancel}
            sx={{ textTransform: "none" }}
            color="error"
          >
            Cancel
          </Button>
        )}
      </Box>

      {/* Right side: Standard MUI footer (pagination, etc.) */}
      {/* @ts-ignore */}
      <GridFooter apiRef={apiRef} sx={{ width: "auto" }} />
    </GridFooterContainer>
  );
};
