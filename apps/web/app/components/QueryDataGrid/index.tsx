"use client";

import { Add, ArrowDownward, ArrowUpward, SwapVert } from "@mui/icons-material";
import { Box, IconButton, Tooltip } from "@mui/material";
import type {
  GridCellParams,
  GridColDef,
  MuiEvent,
} from "@mui/x-data-grid-pro";
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
import type { DataGridRefs, QueryDataGridProps, UIState } from "./types";

export const QueryDataGrid = ({
  queryId,
  columns: externalColumns,
  queryMetadata,
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
  showAddColumn = false,
  onAddColumn,
  onRefsChange,
  notify = false,
  userEmail,
  autoDownload = false,
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
          notify,
          userEmail,
        });
      } else {
        // No sort - refetch without sort params
        fetchQuery(queryId, {
          useSSE,
          pageSize,
          notify,
          userEmail,
        });
      }
    },
    [
      onSortModelChange,
      fetchQuery,
      queryId,
      useSSE,
      pageSize,
      notify,
      userEmail,
    ],
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

  // Helper to find canonical column from metadata
  const getColumnMetadata = useCallback(
    (field: string) => {
      return queryMetadata?.columns?.find(
        (c) => c.id === field || c.column_name === field,
      );
    },
    [queryMetadata],
  );

  // Custom sort click handler - separate from column header selection
  const handleSortClick = useCallback(
    (field: string) => (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation(); // Prevent triggering column selection

      const currentSort = sortModel[0];
      const direction =
        currentSort?.field === field && currentSort?.sort !== "asc"
          ? "asc"
          : "desc";

      handleSortModelChange([{ field, sort: direction }]);
    },
    [sortModel, handleSortModelChange],
  );

  // Enhance columns with descriptions, tooltips, and custom sort buttons
  const columns = useMemo(() => {
    const enhancedColumns: GridColDef[] = externalColumns.map((col) => {
      const metadata = getColumnMetadata(col.field);
      const description =
        metadata?.column_description || col.headerName || col.field;

      return {
        ...col,
        // Disable built-in sorting - we use custom sort buttons
        sortable: false,
        // Add highlight class when column is active
        headerClassName:
          activeColumn?.field === col.field ? "highlight-column-header" : "",
        // Custom header with tooltip and sort button
        renderHeader: (params: any) => (
          <Tooltip title={description}>
            <Box display="flex" alignItems="center">
              <span>{params.colDef.headerName}</span>
              <IconButton size="small" onClick={handleSortClick(col.field)}>
                {sortModel[0]?.field === col.field &&
                  sortModel[0]?.sort === "asc" && (
                    <ArrowDownward sx={{ fontSize: 16 }} />
                  )}
                {sortModel[0]?.field === col.field &&
                  sortModel[0]?.sort === "desc" && (
                    <ArrowUpward sx={{ fontSize: 16 }} />
                  )}
                {(!sortModel[0] || sortModel[0]?.field !== col.field) && (
                  <SwapVert color="disabled" sx={{ fontSize: 16 }} />
                )}
              </IconButton>
            </Box>
          </Tooltip>
        ),
      };
    });

    // Add NEW COLUMN button if enabled
    if (showAddColumn && onAddColumn) {
      const addColumnDef: GridColDef = {
        field: "__add_column__",
        headerName: "",
        sortable: false,
        filterable: false,
        width: 70,
        disableColumnMenu: true,
        renderHeader: () => (
          <Box
            display="flex"
            justifyContent="center"
            alignItems="center"
            height="100%"
          >
            <Tooltip title="Add new column">
              <IconButton
                size="small"
                color="primary"
                onClick={(e) => {
                  e.stopPropagation();
                  onAddColumn();
                }}
                sx={{ border: "solid 1px #EF8626" }}
              >
                <Add sx={{ fontSize: "12px" }} />
              </IconButton>
            </Tooltip>
          </Box>
        ),
        renderCell: () => null,
      };
      enhancedColumns.push(addColumnDef);
    }

    return enhancedColumns;
  }, [
    externalColumns,
    activeColumn,
    showAddColumn,
    onAddColumn,
    getColumnMetadata,
    sortModel,
    handleSortClick,
  ]);

  // Compute and expose refs when selection changes
  useEffect(() => {
    if (!onRefsChange) return;

    const refs: DataGridRefs = {};

    // Build cols ref: [column_name, ...values from all rows]
    if (activeColumn && activeColumn.field !== "__add_column__") {
      const colMeta = getColumnMetadata(activeColumn.field);
      const columnName = colMeta?.column_name || activeColumn.field;
      refs.cols = [
        columnName,
        ...rows.map((r) => r[columnName]?.toString() || ""),
      ];
    }

    // Build rows ref: [headers, ...row_values]
    if (activeRows && activeRows.length > 0 && queryMetadata?.columns) {
      const headers = queryMetadata.columns.map(
        (c) => c.column_alias || c.column_name || c.id,
      );
      refs.rows = [
        headers,
        ...activeRows
          .filter(Boolean)
          .map((r) => Object.values(r).slice(1).filter(Boolean)),
      ];
    }

    onRefsChange(refs);
  }, [
    activeColumn,
    activeRows,
    rows,
    queryMetadata,
    getColumnMetadata,
    onRefsChange,
  ]);

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
      notify,
      userEmail,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel, notify, userEmail]);

  const handleFetchWithNotify = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      notify: true,
      userEmail,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel, userEmail]);

  const handleRefresh = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      force: true,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
      notify,
      userEmail,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel, notify, userEmail]);

  const handleRefreshWithNotify = useCallback(() => {
    fetchQuery(queryId, {
      useSSE,
      force: true,
      notify: true,
      userEmail,
      pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, useSSE, pageSize, sortModel, userEmail]);

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
        notify,
        userEmail,
      });
    },
    [fetchQuery, queryId, useSSE, pageSize, sortModel, notify, userEmail],
  );

  // Handle CSV download
  const handleDownload = useCallback(() => {
    if (!rows || rows.length === 0) return;

    // Get column headers from the grid columns (excluding special columns)
    const dataColumns = enhancedColumns.filter(
      (col) => col.field !== "__add_column__" && !col.field.startsWith("__"),
    );
    const headers = dataColumns.map((col) => col.field);

    // Build CSV content
    const csvRows = [
      headers.join(","), // header row
      ...rows.map((row) =>
        headers
          .map((header) => {
            const value = row[header];
            // Escape quotes and wrap in quotes if contains comma, quote, or newline
            if (value === null || value === undefined) return "";
            const str = String(value);
            if (str.includes(",") || str.includes('"') || str.includes("\n")) {
              return `"${str.replace(/"/g, '""')}"`;
            }
            return str;
          })
          .join(","),
      ),
    ];

    const csvContent = csvRows.join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);

    // Create download link and trigger
    const link = document.createElement("a");
    link.href = url;
    link.download = `${queryId}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [rows, enhancedColumns, queryId]);

  // Auto-download when data is ready (triggered by URL param ?download=true)
  const hasAutoDownloaded = useRef(false);
  useEffect(() => {
    if (
      autoDownload &&
      rows.length > 0 &&
      !isFetching &&
      !hasAutoDownloaded.current
    ) {
      hasAutoDownloaded.current = true;
      // Small delay to ensure UI has rendered
      setTimeout(() => {
        handleDownload();
      }, 100);
    }
  }, [autoDownload, rows.length, isFetching, handleDownload]);

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

      // Use _gridId for selection tracking (matches getRowId)
      const rowId = params.row._gridId;

      if (selectionModel.includes(rowId)) {
        // Clicking already-selected row clears selection
        onActiveRowsChange?.(undefined);
        handleSelectionChange([]);
      } else if (mouseEvent.shiftKey || mouseEvent.ctrlKey) {
        // Multi-select with Shift/Ctrl
        onActiveRowsChange?.(
          activeRows ? [...activeRows, params.row] : [params.row],
        );
        handleSelectionChange([...selectionModel, rowId]);
      } else {
        // Single select
        onActiveRowsChange?.([params.row]);
        handleSelectionChange([rowId]);
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
        paginationModel={paginationModel}
        onPaginationModelChange={setPaginationModel}
        disableRowSelectionOnClick
        rowSelectionModel={selectionModel}
        onRowSelectionModelChange={(newSelection) => {
          // Update selection model - clears active column
          handleSelectionChange(newSelection as number[]);
          onActiveColumnChange?.(null);
        }}
        // Disable built-in sort handling - we use custom sort buttons
        onSortModelChange={() => {}}
        rows={rows}
        rowCount={totalRows}
        columns={columns}
        getRowId={(row) => row._gridId}
        loading={isFetching}
        onColumnHeaderClick={handleColumnHeaderClick}
        onCellClick={handleCellClick}
        getRowClassName={(params) => {
          // Check if this row is in activeRows by matching _gridId
          const isActive = activeRows
            ?.filter(Boolean)
            .some((r: any) => r?._gridId === params.row?._gridId);
          return isActive ? "highlighted-row" : "";
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
              onDownload={handleDownload}
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
