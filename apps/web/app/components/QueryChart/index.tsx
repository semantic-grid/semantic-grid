"use client";

import { alpha, Box, CircularProgress, Typography } from "@mui/material";
import { BarChart, ChartsTooltip, LineChart, PieChart } from "@mui/x-charts";
import React, { useCallback, useMemo } from "react";

import { useData } from "@/app/contexts/DataContext";
import {
  buildGridColumns,
  buildPieChartSeries,
  normalizeDataSet,
} from "@/app/helpers/chart";

import { ErrorOverlay, FetchOverlay, LoadingOverlay } from "./overlays";
import type { QueryChartProps } from "./types";

export const QueryChart = ({
  queryId,
  chartType,
  columns,
  queryMetadata,
  height = 400,
  onFetch,
  onFetchWithNotify,
  showNotifyOption = false,
  estimatedRows,
  estimatedSizeGb,
}: QueryChartProps) => {
  const { getQueryState, fetchQuery, hasCachedData, isStale } = useData();

  // Get current query state
  const queryState = getQueryState(queryId);
  const { status, rows, error, isFetching } = queryState;

  // Build column definitions from metadata using existing helper
  const gridColumns = useMemo(() => {
    if (!queryMetadata) return [];
    return buildGridColumns(queryMetadata);
  }, [queryMetadata]);

  // Normalize dataset for charts using existing helper (handles date conversion)
  const dataset = useMemo(() => {
    if (!rows || rows.length === 0 || gridColumns.length === 0) return [];
    return normalizeDataSet(rows, gridColumns);
  }, [rows, gridColumns]);

  // X-axis configuration - use field without col_ prefix (matches normalizeDataSet)
  const xAxis = useMemo(() => {
    if (gridColumns.length === 0) return [];
    const firstCol = gridColumns[0];
    const dataKey = firstCol?.field?.replace("col_", "") || "";
    return [
      {
        dataKey,
        scaleType: chartType === "bar" ? "band" : "time",
        valueFormatter: (value: Date) =>
          value instanceof Date ? value.toLocaleDateString() : String(value),
      },
    ];
  }, [gridColumns, chartType]);

  // Series configuration for line/bar charts - use field without col_ prefix
  const series = useMemo(() => {
    if (gridColumns.length < 2) return [];
    // Skip first column (x-axis), use remaining numeric columns as series
    return gridColumns.slice(1).map((col) => ({
      id: col.field?.replace("col_", ""),
      label: col.headerName,
      dataKey: col.field?.replace("col_", ""),
      showMark: false,
    }));
  }, [gridColumns]);

  // Pie chart series - use existing helper with RAW rows (not normalized dataset)
  // because buildPieChartSeries expects string labels, not Date objects
  const pieSeries = useMemo(() => {
    if (gridColumns.length < 2 || rows.length === 0) return [];
    return buildPieChartSeries(rows, gridColumns);
  }, [gridColumns, rows]);

  // Fetch handlers
  const handleFetch = useCallback(() => {
    if (onFetch) {
      onFetch();
    } else {
      fetchQuery(queryId, { pageSize: 100 });
    }
  }, [onFetch, fetchQuery, queryId]);

  const handleFetchWithNotify = useCallback(() => {
    if (onFetchWithNotify) {
      onFetchWithNotify();
    } else {
      fetchQuery(queryId, { pageSize: 100, notify: true });
    }
  }, [onFetchWithNotify, fetchQuery, queryId]);

  // Determine UI state
  const hasData = hasCachedData(queryId) && dataset.length > 0;
  const stale = isStale(queryId);

  // Show fetch overlay if no data
  if (!hasData && status !== "pending" && !isFetching) {
    return (
      <Box
        sx={{
          width: "100%",
          height,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <FetchOverlay
          onFetch={handleFetch}
          onFetchWithNotify={handleFetchWithNotify}
          showNotifyOption={showNotifyOption}
          estimatedRows={estimatedRows}
          estimatedSizeGb={estimatedSizeGb}
        />
      </Box>
    );
  }

  // Show loading if fetching and no data
  if ((isFetching || status === "pending") && !hasData) {
    return (
      <Box
        sx={{
          width: "100%",
          height,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <LoadingOverlay />
      </Box>
    );
  }

  // Show error
  if (status === "error" && !hasData) {
    return (
      <Box
        sx={{
          width: "100%",
          height,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <ErrorOverlay error={error || "Unknown error"} onRetry={handleFetch} />
      </Box>
    );
  }

  // No data after fetch
  if (hasData && dataset.length === 0) {
    return (
      <Box
        sx={{
          width: "100%",
          height,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <Typography color="text.secondary">No data to display</Typography>
      </Box>
    );
  }

  // Render chart based on type
  const renderChart = () => {
    switch (chartType) {
      case "pie":
        return (
          <PieChart series={pieSeries} height={height} sx={{ width: "100%" }} />
        );
      case "bar":
        return (
          <BarChart
            xAxis={xAxis as any}
            series={series}
            dataset={dataset}
            height={height}
            sx={{ width: "100%" }}
          >
            <ChartsTooltip />
          </BarChart>
        );
      case "line":
      default:
        return (
          <LineChart
            xAxis={xAxis as any}
            series={series}
            dataset={dataset}
            height={height}
            sx={{ width: "100%" }}
          >
            <ChartsTooltip />
          </LineChart>
        );
    }
  };

  return (
    <Box sx={{ width: "100%", height, position: "relative" }}>
      {renderChart()}
      {/* Loading overlay when refreshing with existing data */}
      {(isFetching || stale) && hasData && (
        <Box
          position="absolute"
          top={0}
          left={0}
          right={0}
          bottom={0}
          display="flex"
          justifyContent="center"
          alignItems="center"
          bgcolor={(theme) => alpha(theme.palette.background.default, 0.6)}
        >
          <CircularProgress size={24} />
        </Box>
      )}
    </Box>
  );
};

export * from "./types";
