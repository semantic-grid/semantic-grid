"use client";

import type { GridCellParams, MuiEvent } from "@mui/x-data-grid-pro";
import { DataGridPro, useGridApiRef } from "@mui/x-data-grid-pro";
import React, { useCallback, useEffect, useMemo, useState } from "react";

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
  sql,
  columns,
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
  const { getQueryState, fetchQuery, cancelFetch, isStale, hasCachedData } =
    useData();

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
    },
    [onSortModelChange],
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

  // Determine UI state based on query state
  const uiState = useMemo((): UIState => {
    const hasCache = hasCachedData(queryId);
    const stale = isStale(queryId);

    if (status === "error") {
      return "error";
    }

    if (!hasCache) {
      if (isFetching || status === "pending") {
        return "no_cache_pending";
      }
      return performanceWarning
        ? "no_cache_no_pending_warning"
        : "no_cache_no_pending";
    }

    // Has cached data
    if (stale) {
      return performanceWarning ? "has_cache_stale_warning" : "has_cache_stale";
    }

    return "has_cache_fresh";
  }, [queryId, status, isFetching, performanceWarning, hasCachedData, isStale]);

  // Action handlers
  const handleFetch = useCallback(() => {
    fetchQuery(queryId, sql, {
      limit: pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, sql, pageSize, sortModel]);

  const handleFetchWithNotify = useCallback(() => {
    fetchQuery(queryId, sql, {
      notify: true,
      limit: pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, sql, pageSize, sortModel]);

  const handleRefresh = useCallback(() => {
    fetchQuery(queryId, sql, {
      force: true,
      limit: pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, sql, pageSize, sortModel]);

  const handleRefreshWithNotify = useCallback(() => {
    fetchQuery(queryId, sql, {
      force: true,
      notify: true,
      limit: pageSize,
      sortBy: sortModel[0]?.field,
      sortOrder: sortModel[0]?.sort || undefined,
    });
  }, [fetchQuery, queryId, sql, pageSize, sortModel]);

  const handleCancel = useCallback(() => {
    cancelFetch(queryId);
  }, [cancelFetch, queryId]);

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

  // Show spinner overlay when revalidating with existing data
  const showSpinnerOverlay =
    (uiState === "has_cache_stale" || uiState === "has_cache_fresh") &&
    isValidating;

  return (
    <>
      {showSpinnerOverlay && <SpinnerOverlay />}
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
          footer: () => (
            <QueryDataGridFooter
              isFetching={isFetching}
              isValidating={isValidating}
              showNotifyOption={performanceWarning}
              onRefresh={handleRefresh}
              onRefreshWithNotify={handleRefreshWithNotify}
              onCancel={handleCancel}
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
    </>
  );
};

export * from "./types";
