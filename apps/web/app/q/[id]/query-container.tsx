"use client";

import { Box, Container } from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid-pro";
import React, { useContext, useMemo, useState } from "react";

import { QueryDataGrid } from "@/app/components/QueryDataGrid";
import { ScrollLockWrapper } from "@/app/components/ScrollLockWrapper";
import HighlightedSQL from "@/app/components/SqlView";
import { AppContext } from "@/app/contexts/App";
import { buildGridColumns } from "@/app/helpers/chart";
import type { TQuery } from "@/app/lib/types";

export interface IQueryContainerProps {
  query?: TQuery;
  id?: string;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const CustomTabPanel = (props: TabPanelProps) => {
  const { children, value, index, ...other } = props;

  return (
    <Box
      role="tabpanel"
      hidden={value !== index}
      id={`simple-tabpanel-${index}`}
      aria-labelledby={`simple-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ pb: 3 }}>{children}</Box>}
    </Box>
  );
};

export const QueryContainer = ({ id, query }: IQueryContainerProps) => {
  const { tab } = useContext(AppContext);

  // Build grid columns from query metadata
  const gridColumns = useMemo(() => {
    if (!query) return [];
    return buildGridColumns(query);
  }, [query]);

  // Selection state (managed here, passed to QueryDataGrid)
  const [activeColumn, setActiveColumn] = useState<GridColDef | null>(null);
  const [activeRows, setActiveRows] = useState<any[] | undefined>(undefined);
  const [selectionModel, setSelectionModel] = useState<number[]>([]);

  if (!query || !id) {
    return null;
  }

  // Performance warning is nested in explanation for TQuery type
  const performanceWarning = query.explanation?.performance_warning;
  const estimatedRows = query.explanation?.estimated_rows;
  const estimatedSizeGb = query.explanation?.estimated_size_gb;

  return (
    <Box
      sx={{
        marginTop: "50px", // padding to avoid overlap with app bar
        height: "calc(100vh - 50px)",
      }}
    >
      <Box sx={{ overflow: "hidden", height: "100%" }}>
        <Container
          sx={{
            position: "relative",
            width: "100%",
            height: "100%",
          }}
          maxWidth={false}
        >
          <Box sx={{ height: "100%" }}>
            <CustomTabPanel value={tab} index={0}>
              <Box sx={{ height: "calc(100vh - 120px)" }}>
                <ScrollLockWrapper>
                  <QueryDataGrid
                    queryId={query.query_id}
                    columns={gridColumns}
                    queryMetadata={query}
                    paginate={true}
                    pageSize={100}
                    performanceWarning={performanceWarning}
                    estimatedRows={estimatedRows}
                    estimatedSizeGb={estimatedSizeGb}
                    activeColumn={activeColumn}
                    onActiveColumnChange={setActiveColumn}
                    activeRows={activeRows}
                    onActiveRowsChange={setActiveRows}
                    selectionModel={selectionModel}
                    onSelectionModelChange={setSelectionModel}
                  />
                </ScrollLockWrapper>
              </Box>
            </CustomTabPanel>
            <CustomTabPanel value={tab} index={1}>
              <Box
                sx={{
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
            </CustomTabPanel>
          </Box>
        </Container>
      </Box>
    </Box>
  );
};
