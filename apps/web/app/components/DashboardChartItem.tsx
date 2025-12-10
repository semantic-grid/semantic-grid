"use client";

import { Box, CircularProgress } from "@mui/material";
import React, { useEffect } from "react";

import { QueryChart } from "@/app/components/QueryChart";
import type { ChartType } from "@/app/components/QueryChart/types";
import { useData } from "@/app/contexts/DataContext";
import { useQueryObject } from "@/app/hooks/useQueryObject";

export const DashboardChartItem = ({
  queryUid,
  chartType,
  minHeight = 300,
}: {
  queryUid: string;
  chartType: string;
  minHeight?: number;
}) => {
  const { data: query, isLoading: isLoadingQuery } = useQueryObject(queryUid);
  const { fetchQuery, hasCachedData } = useData();

  // Auto-fetch data for dashboard items (limited to 100 rows for charts)
  useEffect(() => {
    if (queryUid && !hasCachedData(queryUid)) {
      fetchQuery(queryUid, { pageSize: 100, paginate: false });
    }
  }, [queryUid, hasCachedData, fetchQuery]);

  // Show loading while query metadata is loading
  if (isLoadingQuery || !query) {
    return (
      <Box
        sx={{
          width: "100%",
          height: minHeight,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  // Validate chart type
  const validChartType: ChartType =
    chartType === "line" || chartType === "bar" || chartType === "pie"
      ? chartType
      : "line";

  return (
    <QueryChart
      queryId={queryUid}
      chartType={validChartType}
      queryMetadata={query}
      height={minHeight}
    />
  );
};
