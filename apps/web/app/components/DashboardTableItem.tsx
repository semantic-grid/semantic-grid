"use client";

import { Box, CircularProgress } from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid-pro";
import React, { useEffect, useMemo } from "react";

import { QueryDataGrid } from "@/app/components/QueryDataGrid";
import { useData } from "@/app/contexts/DataContext";
import { buildGridColumns } from "@/app/helpers/chart";
import { useQueryObject } from "@/app/hooks/useQueryObject";

export const DashboardTableItem = ({
  queryUid,
  minHeight,
}: {
  queryUid: string;
  minHeight: number;
}) => {
  const { data: query, isLoading: isLoadingQuery } = useQueryObject(queryUid);
  const { fetchQuery, hasCachedData } = useData();

  // Build columns from query metadata
  const gridColumns: GridColDef[] = useMemo(() => {
    if (!query) return [];
    return buildGridColumns(query);
  }, [query]);

  // Auto-fetch data for dashboard items
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

  return (
    <Box sx={{ height: minHeight }}>
      <QueryDataGrid
        queryId={queryUid}
        columns={gridColumns}
        queryMetadata={query}
        paginate={false}
        pageSize={100}
      />
    </Box>
  );
};
