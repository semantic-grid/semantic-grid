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

  const gridColumns: GridColDef[] = useMemo(() => {
    if (!query) return [];
    return buildGridColumns(query);
  }, [query]);

  // Guess chart type if not provided
  const guessedChartType = useMemo((): ChartType => {
    if (chartType === "line" || chartType === "bar" || chartType === "pie") {
      return chartType;
    }
    // Guess based on first column type
    if (timeKey(gridColumns[0]?.type)) return "bar";
    return "pie";
  }, [chartType, gridColumns]);

  const {
    view,
    chartType: selectedChartType,
    setChartType,
  } = useItemViewContext();

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
