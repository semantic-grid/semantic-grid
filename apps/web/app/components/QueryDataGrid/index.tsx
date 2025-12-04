"use client";

import { Box } from "@mui/material";
import type { GridCellParams, MuiEvent } from "@mui/x-data-grid-pro";
import { DataGridPro, useGridApiRef } from "@mui/x-data-grid-pro";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useData } from "@/app/contexts/DataContext";

import { QueryDataGridFooter } from "./footer";
import {
  ErrorOverlay,
  FetchOverlay,
  LoadingOverlay,
  NoDataOverlay,
  SpinnerOverlay,
} from "./overlays";
import type { QueryDataGridProps, UIState } from "./types";

export const QueryDataGrid = ({
  queryId,
  columns,
  useSSE = true,
  paginate = true,
  performanceWarning = false,
  estimatedRows,
  estimatedSizeGb,
  sortModel: externalSortModel,
  onSortModelChange,
  activeColumn,
  onActiveColumnChange,
  activeRows,
  onActiveRowsChange,
  selectionModel: externalSelectionModel,
  onSelectionModelChange,
  pageSize = 100,
}: QueryDataGridProps) => {
  const apiRef = useGridApiRef();
  const gridRef = useRef<HTMLDivElement>(null);
  const {
    getQueryState,
    fetchQuery,
    loadMore,
    cancelFetch,
    isStale,
    hasCachedData,
    isReachingEnd,
  } = useData();

  // Internal state for sort/selection if not controlled externally
  const [internalSortModel, setInternalSortModel] = useState(
    externalSortModel || [],
  );
  const [internalSelectionModel, setInternalSelectionModel] = useState<
    number[]
  >(externalSelectionModel || []);
  const [paginationModel, setPaginationModel] = useState({
    page: 0,
    pageSize,
  });

  const sortModel = externalSortModel ?? internalSortModel;
  const selectionModel = externalSelectionModel ?? internalSelectionModel;

  const handleSortModelChange = useCallback(
    (newModel: typeof sortModel) => {
      if (onSortModelChange) {
        onSortModelChange(newModel);
      } else {
        setInternalSortModel(newModel);
      }

      // Trigger server-side sort by refetching with new sort params
      if (newModel.length > 0 && newModel[0]) {
        fetchQuery(queryId, {
          useSSE,
          pageSize,
          sortBy: newModel[0].field,
          sortOrder: newModel[0].sort ?? undefined,
        });
      } else {
        // No sort - refetch without sort params
        fetchQuery(queryId, {
          useSSE,
          pageSize,
        });
      }
    },
    [onSortModelChange, fetchQuery, queryId, useSSE, pageSize],
  );

  const handleSelectionChange = useCallback(
    (newSelection: number[]) => {
      if (onSelectionModelChange) {
        onSelectionModelChange(newSelection);
      } else {
        setInternalSelectionModel(newSelection);
      }
    },
    [onSelectionModelChange],
  );

  // Get current query state
  const queryState = getQueryState(queryId);
  const {
    status,
    rows: rawRows,
    totalRows,
    error,
    isFetching,
    isValidating,
  } = queryState;

  // Ensure rows have unique IDs - stabilize with length check
  const rows = useMemo(() => {
    if (rawRows.length === 0) return [];
    return rawRows.map((row, index) => ({
      ...row,
      _gridId: row.id ?? index,
    }));
  }, [rawRows]);

  // Infinite scroll: load more when nearing bottom
  useEffect(() => {
    if (!paginate) return; // Skip if pagination disabled (fetch all mode)

    const grid = gridRef.current;
    if (!grid) return;

    const scrollable = grid.querySelector(
      ".MuiDataGrid-virtualScroller",
    ) as HTMLDivElement;
    if (!scrollable) return;

    const handleScroll = () => {
      const { scrollTop, clientHeight, scrollHeight } = scrollable;
      const nearBottom =
        scrollTop + clientHeight >= scrollHeight - clientHeight * 1.5;

      if (
        nearBottom &&
        !isReachingEnd(queryId) &&
        !isFetching &&
        !isValidating
      ) {
        console.log("[QueryDataGrid] Nearing bottom, loading more...");
        loadMore(queryId, {
          useSSE,
          pageSize,
          sortBy: sortModel[0]?.field,
          sortOrder: sortModel[0]?.sort ?? undefined,
        });
      }
    };

    scrollable.addEventListener("scroll", handleScroll);
    return () => scrollable.removeEventListener("scroll", handleScroll);
  }, [
    paginate,
    queryId,
    isFetching,
    isValidating,
    isReachingEnd,
    loadMore,
    useSSE,
    pageSize,
    sortModel,
  ]);

  // Determine UI state based on query state
  // Key insight: if we have rows displayed, keep showing them during refetch (sort, pagination)
  const uiState = useMemo((): UIState => {
    const hasCache = hasCachedData(queryId);
    const hasDisplayedRows = rows.length > 0;
    const stale = isStale(queryId);

    if (status === "error" && !hasDisplayedRows) {
      return "error";
    }

    // If we have rows on screen, don't show loading overlay - use spinner instead
    if (hasDisplayedRows) {
      if (stale) {
        return performanceWarning
          ? "has_cache_stale_warning"
          : "has_cache_stale";
      }
      return "has_cache_fresh";
    }

    if (!hasCache) {
      if (isFetching || status === "pending") {
        return "no_cache_pending";
      }
      return performanceWarning
        ? "no_cache_no_pending_warning"
        : "no_cache_no_pending";
    }

    // Has cached data but no rows displayed yet
    if (stale) {
      return performanceWarning ? "has_cache_stale_warning" : "has_cache_stale";
    }

    return "has_cache_fresh";
  }, [
    queryId,
    status,
    rows.length,
    isFetching,
    performanceWarning,
    hasCachedData,
    isStale,
  ]);

  // Action handlers
  const handleFetch = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel]);

  const handleFetchWithNotify = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      notify: true,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel]);

  const handleRefresh = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      force: true,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel]);

  const handleRefreshWithNotify = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      force: true,
      notify: true,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel]);

  const handleCancel = useCallback(() => {
    cancelFetch(queryId);
  }, [cancelFetch, queryId]);

  // Handle classic pagination page change
  const handlePageChange = useCallback(
    (newPage: number) => {
      setPaginationModel((prev) => ({ ...prev, page: newPage }));
      const newOffset = newPage * pageSize;
      fetchQuery(queryId, {
        useSSE,
        pageSize,
        offset: newOffset,
        paginate: true,
        sortBy: sortModel[0]?.field,
        sortOrder: sortModel[0]?.sort ?? undefined,
      });
    },
    [fetchQuery, queryId, useSSE, pageSize, sortModel],
  );

  // Determine the overlay component based on UI state
  const noRowsOverlayComponent = useMemo(() => {
    switch (uiState) {
      case "error":
        // eslint-disable-next-line react/no-unstable-nested-components
        return () => (
          <ErrorOverlay
            error={error || "Unknown error"}
            onRetry={handleFetch}
          />
        );
      case "no_cache_pending":
        // eslint-disable-next-line react/no-unstable-nested-components
        return () => <LoadingOverlay onCancel={handleCancel} />;
      case "no_cache_no_pending":
      case "no_cache_no_pending_warning":
        // eslint-disable-next-line react/no-unstable-nested-components
        return () => (
          <FetchOverlay
            onFetch={handleFetch}
            onFetchWithNotify={handleFetchWithNotify}
            showNotifyOption={performanceWarning}
            estimatedRows={estimatedRows}
            estimatedSizeGb={estimatedSizeGb}
          />
        );
      case "has_cache_stale_warning":
        // Show refresh button overlay for stale data with warning
        // eslint-disable-next-line react/no-unstable-nested-components
        return () => (
          <FetchOverlay
            onFetch={handleRefresh}
            onFetchWithNotify={handleRefreshWithNotify}
            showNotifyOption={true}
            estimatedRows={estimatedRows}
            estimatedSizeGb={estimatedSizeGb}
            isStale={true}
          />
        );
      default:
        return NoDataOverlay;
    }
  }, [
    uiState,
    error,
    handleFetch,
    handleFetchWithNotify,
    handleRefresh,
    handleRefreshWithNotify,
    handleCancel,
    performanceWarning,
    estimatedRows,
    estimatedSizeGb,
  ]);

  // Cell/column click handlers
  const handleColumnHeaderClick = useCallback(
    (params: { colDef: (typeof columns)[number] }) => {
      if (onActiveColumnChange) {
        if (activeColumn && activeColumn.field === params.colDef.field) {
          onActiveColumnChange(null);
        } else {
          onActiveColumnChange(params.colDef);
        }
      }
      handleSelectionChange([]);
      onActiveRowsChange?.(undefined);
    },
    [
      activeColumn,
      onActiveColumnChange,
      handleSelectionChange,
      onActiveRowsChange,
    ],
  );

  const handleCellClick = useCallback(
    (params: GridCellParams, event: MuiEvent<React.MouseEvent>) => {
      const mouseEvent = event as React.MouseEvent;
      onActiveColumnChange?.(null);

      if (selectionModel.includes(params.row.id)) {
        onActiveRowsChange?.(undefined);
        handleSelectionChange([]);
      } else if (mouseEvent.shiftKey || mouseEvent.ctrlKey) {
        onActiveRowsChange?.(
          activeRows ? [...activeRows, params.row] : [params.row],
        );
        handleSelectionChange([...selectionModel, params.row.id]);
      } else {
        onActiveRowsChange?.([params.row]);
        handleSelectionChange([params.row.id]);
      }
    },
    [
      selectionModel,
      activeRows,
      onActiveColumnChange,
      onActiveRowsChange,
      handleSelectionChange,
    ],
  );

  return (
    <Box ref={gridRef} sx={{ width: "100%", height: "100%" }}>
      <DataGridPro
        apiRef={apiRef}
        density="compact"
        sortingMode="server"
        paginationMode="server"
        sortModel={sortModel}
        disableMultipleRowSelection={false}
        onSortModelChange={handleSortModelChange}
        paginationModel={paginationModel}
        onPaginationModelChange={setPaginationModel}
        disableRowSelectionOnClick
        rowSelectionModel={selectionModel}
        onRowSelectionModelChange={(newSelection) => {
          handleSelectionChange(newSelection as number[]);
          onActiveColumnChange?.(null);
        }}
        rows={rows}
        rowCount={totalRows}
        columns={columns}
        getRowId={(row) => row._gridId}
        loading={isFetching}
        onColumnHeaderClick={handleColumnHeaderClick}
        onCellClick={handleCellClick}
        getRowClassName={(params) => {
          if (
            activeRows
              ?.filter(Boolean)
              .find((r: any) => r?.id === params.row?.id)
          ) {
            return "highlighted-row";
          }
          return "";
        }}
        getCellClassName={(params) => {
          if (
            params.colDef.type === "checkboxSelection" ||
            params.colDef.field === "__check__"
          ) {
            return "";
          }
          return activeColumn?.field === params.field ? "highlight-column" : "";
        }}
        slots={{
          noRowsOverlay: noRowsOverlayComponent,
          // eslint-disable-next-line react/no-unstable-nested-components
          loadingOverlay: () => <SpinnerOverlay onCancel={handleCancel} />,
          // eslint-disable-next-line react/no-unstable-nested-components
          footer: () => (
            <QueryDataGridFooter
              isFetching={isFetching}
              isValidating={isValidating}
              showNotifyOption={performanceWarning}
              onRefresh={handleRefresh}
              onRefreshWithNotify={handleRefreshWithNotify}
              onCancel={handleCancel}
              paginationMode={paginate ? "infinite" : "classic"}
              currentRows={rows.length}
              totalRows={totalRows}
              page={paginationModel.page}
              pageSize={paginationModel.pageSize}
              onPageChange={handlePageChange}
            />
          ),
        }}
        sx={{
          border: "none",
          fontSize: "1rem",
          "& .highlight-column": {
            backgroundColor: "rgba(255, 165, 0, 0.1)",
          },
          "& .MuiDataGrid-cell:focus": {
            outline: "none",
          },
          "& .MuiDataGrid-cell:focus-within": {
            outline: "none",
          },
          "& .MuiDataGrid-columnHeader:focus": {
            outline: "none",
          },
          "& .MuiDataGrid-columnHeader:focus-within": {
            outline: "none",
          },
          "& .highlight-column-header": {
            backgroundColor: "rgba(255, 165, 0, 0.1) !important",
          },
          "& .highlighted-row": {
            backgroundColor: "rgba(255, 165, 0, 0.1)",
          },
        }}
      />
    </Box>
  );
};

export * from "./types";
