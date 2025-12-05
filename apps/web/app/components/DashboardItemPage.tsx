"use client";

import { Box, Container, Paper, Typography } from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid";
import React, { useEffect, useMemo } from "react";

import { QueryChart } from "@/app/components/QueryChart";
import type { ChartType } from "@/app/components/QueryChart/types";
import { QueryDataGrid } from "@/app/components/QueryDataGrid";
import HighlightedSQL from "@/app/components/SqlView";
import { useData } from "@/app/contexts/DataContext";
import { useItemViewContext } from "@/app/contexts/ItemView";
import { buildGridColumns, timeKey } from "@/app/helpers/chart";
import { useAppUser } from "@/app/hooks/useAppUser";
import type { TQuery } from "@/app/lib/types";

export const DashboardItemPage = ({
  id,
  query,
  name,
  itemType,
  chartType,
}: {
  id: string;
  query?: TQuery;
  name?: string;
  itemType?: string;
  chartType?: string;
}) => {
  const { fetchQuery, hasCachedData } = useData();
  const { user: appUser } = useAppUser();

  const gridColumns: GridColDef[] = useMemo(() => {
    if (!query) return [];
    return buildGridColumns(query);
  }, [query]);

  // Guess chart type if not provided
  const guessedChartType = useMemo((): ChartType => {
    if (chartType === "line" || chartType === "bar" || chartType === "pie") {
      return chartType;
    }
    // Guess based on first column type (use _dbType for original DB type)
    const firstColType =
      (gridColumns[0] as any)?._dbType || gridColumns[0]?.type;
    if (timeKey(firstColType)) return "line"; // Time series -> line chart
    return "pie"; // Categorical -> pie chart
  }, [chartType, gridColumns]);

  const {
    view,
    chartType: selectedChartType,
    setChartType,
    setAvailableChartTypes,
  } = useItemViewContext();

  // Determine available chart types based on data shape
  // Time series data: line, bar (not pie)
  // Categorical data: pie, bar (not line)
  const isTimeSeries = useMemo(() => {
    if (gridColumns.length === 0) return false;
    const firstColType =
      (gridColumns[0] as any)?._dbType || gridColumns[0]?.type;
    return timeKey(firstColType);
  }, [gridColumns]);

  // Set available chart types based on data shape
  useEffect(() => {
    if (isTimeSeries) {
      setAvailableChartTypes(["line", "bar"]);
    } else {
      setAvailableChartTypes(["pie", "bar"]);
    }
  }, [isTimeSeries, setAvailableChartTypes]);

  // Set initial chart type based on guessed value
  useEffect(() => {
    if (guessedChartType) {
      setChartType(guessedChartType);
    }
  }, [guessedChartType, setChartType]);

  // Auto-fetch data if not cached
  useEffect(() => {
    if (query?.query_id && !hasCachedData(query.query_id)) {
      fetchQuery(query.query_id, { pageSize: 100, paginate: false });
    }
  }, [query?.query_id, hasCachedData, fetchQuery]);

  // Validate selected chart type
  const validChartType: ChartType =
    selectedChartType === "line" ||
    selectedChartType === "bar" ||
    selectedChartType === "pie"
      ? selectedChartType
      : guessedChartType;

  if (!query) {
    return null;
  }

  return (
    <Container maxWidth={false}>
      <Paper elevation={0} sx={{ height: "calc(100vh - 64px)", width: "100%" }}>
        <Typography variant="h6" gutterBottom>
          {name}
        </Typography>
        <Typography variant="body2" gutterBottom>
          {query.summary}
        </Typography>

        <Box sx={{ height: "calc(100vh - 180px)" }}>
          {view === "chart" && (
            <QueryChart
              queryId={query.query_id}
              chartType={validChartType}
              queryMetadata={query}
              height={window?.innerHeight ? window.innerHeight - 200 : 600}
            />
          )}

          {view === "grid" && (
            <QueryDataGrid
              queryId={query.query_id}
              columns={gridColumns}
              queryMetadata={query}
              paginate={false}
              pageSize={100}
              userEmail={appUser?.email}
            />
          )}

          {view === "sql" && (
            <Box
              sx={{
                p: 2,
                "& p": {
                  fontFamily: "monospace",
                  whiteSpace: "pre-wrap",
                  color: "text.secondary",
                },
              }}
            >
              <HighlightedSQL
                code={query?.sql || "No SQL available for this query."}
              />
            </Box>
          )}
        </Box>
      </Paper>
    </Container>
  );
};
