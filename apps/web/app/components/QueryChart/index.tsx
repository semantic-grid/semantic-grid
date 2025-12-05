"use client";

import { alpha, Box, CircularProgress, Typography } from "@mui/material";
import { BarChart, ChartsTooltip, LineChart, PieChart } from "@mui/x-charts";
import React, { useCallback, useMemo } from "react";

import { useData } from "@/app/contexts/DataContext";

import { FetchOverlay, ErrorOverlay, LoadingOverlay } from "./overlays";
import type { QueryChartProps, ChartType } from "./types";

// Helper to detect if column type is datetime
const isDateTimeColumn = (type?: string): boolean => {
  if (!type) return false;
  const lower = type.toLowerCase();
  return (
    lower.includes("date") ||
    lower.includes("time") ||
    lower.includes("timestamp")
  );
};

// Helper to detect if column type is numeric
const isNumericColumn = (type?: string): boolean => {
  if (!type) return false;
  const lower = type.toLowerCase();
  return (
    lower.includes("int") ||
    lower.includes("float") ||
    lower.includes("double") ||
    lower.includes("decimal") ||
    lower.includes("numeric") ||
    lower.includes("bigint") ||
    lower.includes("uint")
  );
};

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

  // Build column definitions from metadata
  const gridColumns = useMemo(() => {
    if (!queryMetadata?.columns) return [];
    return queryMetadata.columns.map((col, idx) => ({
      field: col.column_name || `col_${idx}`,
      headerName: col.column_alias || col.column_name || `col_${idx}`,
      type: col.column_type,
    }));
  }, [queryMetadata]);

  // Normalize dataset for charts (convert dates, ensure proper types)
  const dataset = useMemo(() => {
    if (!rows || rows.length === 0 || gridColumns.length === 0) return [];

    return rows
      .map((row: Record<string, unknown>) =>
        Object.entries(row).reduce(
          (res, [k, v]) => {
            // Find matching column to check type
            const col = gridColumns.find((c) => c.field === k);
            let value: string | number | Date | null | undefined = v as any;

            if (isDateTimeColumn(col?.type)) {
              value = new Date(v?.toString() || Date.now());
            } else if (isNumericColumn(col?.type)) {
              value = Number(v) || 0;
            } else if (v !== null && v !== undefined) {
              value = String(v);
            }

            return { ...res, [k]: value };
          },
          {} as Record<string, string | number | Date | null | undefined>,
        ),
      )
      .sort((a, b) => {
        // Sort by first column if it's datetime
        if (gridColumns.length > 0 && isDateTimeColumn(gridColumns[0]?.type)) {
          const key = gridColumns[0]?.field || "";
          const aTime = (a[key] as Date)?.getTime?.() || 0;
          const bTime = (b[key] as Date)?.getTime?.() || 0;
          return aTime - bTime;
        }
        return 0;
      });
  }, [rows, gridColumns]);

  // X-axis configuration
  const xAxis = useMemo(() => {
    if (gridColumns.length === 0) return [];
    const firstCol = gridColumns[0];
    return [
      {
        dataKey: firstCol?.field,
        scaleType: chartType === "bar" ? "band" : "time",
        valueFormatter: (value: Date) =>
          value instanceof Date ? value.toLocaleDateString() : String(value),
      },
    ];
  }, [gridColumns, chartType]);

  // Series configuration for line/bar charts
  const series = useMemo(() => {
    if (gridColumns.length < 2) return [];
    // Skip first column (x-axis), use remaining numeric columns as series
    return gridColumns.slice(1).map((col) => ({
      id: col.field,
      label: col.headerName,
      dataKey: col.field,
      showMark: false,
    }));
  }, [gridColumns]);

  // Pie chart series
  const pieSeries = useMemo(() => {
    if (gridColumns.length < 2 || dataset.length === 0) return [];

    const categoryCol = gridColumns[0];
    const valueCol = gridColumns[gridColumns.length - 1];

    const seriesData = dataset.map((row) => ({
      id: String(row[categoryCol?.field || ""]),
      label: String(row[categoryCol?.field || ""]),
      value: Number(row[valueCol?.field || ""]) || 0,
    }));

    return [{ data: seriesData }];
  }, [gridColumns, dataset]);

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
