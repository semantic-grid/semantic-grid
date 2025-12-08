"use client";

import {
  Cancel,
  ChevronLeft,
  ChevronRight,
  Download,
  Notifications,
  Refresh,
} from "@mui/icons-material";
import { Box, Button, IconButton, styled, Typography } from "@mui/material";
import { GridFooterContainer, useGridApiContext } from "@mui/x-data-grid-pro";

import { pulse } from "@/app/components/dancing-balls";

const PulsingMonoText = styled(Typography)(({ theme }) => ({
  fontFamily: theme.typography.caption.fontFamily,
  animation: `${pulse} 1.5s ease-in-out infinite`,
}));

export type PaginationMode = "infinite" | "classic";

interface QueryDataGridFooterProps {
  isFetching: boolean;
  isValidating: boolean;
  showNotifyOption: boolean;
  compact?: boolean;
  onRefresh: () => void;
  onRefreshWithNotify: () => void;
  onCancel: () => void;
  onDownload?: () => void;
  // Pagination
  paginationMode?: PaginationMode;
  currentRows: number;
  totalRows: number;
  page: number;
  pageSize: number;
  onPageChange?: (page: number) => void;
}

export const QueryDataGridFooter = ({
  isFetching,
  isValidating,
  showNotifyOption,
  compact = false,
  onRefresh,
  onRefreshWithNotify,
  onCancel,
  onDownload,
  paginationMode = "infinite",
  currentRows,
  totalRows,
  page,
  pageSize,
  onPageChange,
}: QueryDataGridFooterProps) => {
  const apiRef = useGridApiContext();
  const isFetchingMore = isValidating && !isFetching;

  // Classic pagination calculations
  const totalPages = Math.ceil(totalRows / pageSize);
  const canGoPrev = page > 0;
  const canGoNext = page < totalPages - 1;
  const startRow = page * pageSize + 1;
  const endRow = Math.min((page + 1) * pageSize, totalRows);

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

        {!compact && !isFetching && !isValidating && (
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

        {!compact && (isFetching || isValidating) && (
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

      {/* Right side: Download + Pagination info */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        {onDownload && currentRows > 0 && (
          <IconButton
            size="small"
            onClick={onDownload}
            disabled={isFetching}
            title="Download CSV"
          >
            <Download fontSize="small" />
          </IconButton>
        )}
        {paginationMode === "infinite" ? (
          // Infinite scroll: show "Total Rows: X of Y"
          <Typography variant="body2" color="text.secondary">
            Total Rows: {currentRows.toLocaleString()} of{" "}
            {totalRows.toLocaleString()}
          </Typography>
        ) : (
          // Classic paging: show page navigation
          <>
            <Typography variant="body2" color="text.secondary">
              {totalRows > 0
                ? `${startRow.toLocaleString()}-${endRow.toLocaleString()} of ${totalRows.toLocaleString()}`
                : "0 rows"}
            </Typography>
            <IconButton
              size="small"
              onClick={() => onPageChange?.(page - 1)}
              disabled={!canGoPrev || isFetching}
            >
              <ChevronLeft />
            </IconButton>
            <IconButton
              size="small"
              onClick={() => onPageChange?.(page + 1)}
              disabled={!canGoNext || isFetching}
            >
              <ChevronRight />
            </IconButton>
          </>
        )}
      </Box>
    </GridFooterContainer>
  );
};
