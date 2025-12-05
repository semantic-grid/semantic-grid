"use client";

import {
  BarChart,
  Code,
  ShowChart,
  PieChart as PieChartIcon,
  TableChart,
} from "@mui/icons-material";
import {
  Box,
  Tab,
  Tabs,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
} from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid-pro";
import React, { useCallback, useMemo, useState } from "react";

import HighlightedSQL from "@/app/components/SqlView";
import { QueryChart } from "@/app/components/QueryChart";
import type { ChartType } from "@/app/components/QueryChart/types";
import { QueryDataGrid } from "@/app/components/QueryDataGrid";
import type { TQuery } from "@/app/lib/types";

export type ViewType = "grid" | "chart" | "sql";

export interface QueryDataViewProps {
  /** Query ID */
  queryId: string;

  /** Column definitions for grid */
  columns: GridColDef[];

  /** Query metadata */
  queryMetadata?: TQuery | null;

  /** SQL string for SQL view */
  sql?: string;

  /** Default view to show */
  defaultView?: ViewType;

  /** Default chart type */
  defaultChartType?: ChartType;

  /** Show view switching tabs */
  allowViewSwitch?: boolean;

  /** Show chart type selector (only when view=chart) */
  allowChartTypeSwitch?: boolean;

  /** Available chart types (from metadata) */
  availableChartTypes?: ChartType[];

  /** Height for chart view */
  chartHeight?: number;

  // Props passed through to QueryDataGrid
  useSSE?: boolean;
  paginate?: boolean;
  pageSize?: number;
  performanceWarning?: boolean;
  estimatedRows?: number;
  estimatedSizeGb?: number;
  sortModel?: any[];
  onSortModelChange?: (model: any[]) => void;
  activeColumn?: GridColDef | null;
  onActiveColumnChange?: (column: GridColDef | null) => void;
  activeRows?: any[];
  onActiveRowsChange?: (rows: any[] | undefined) => void;
  selectionModel?: number[];
  onSelectionModelChange?: (selection: number[]) => void;
  showAddColumn?: boolean;
  onAddColumn?: () => void;
  onRefsChange?: (refs: any) => void;
  notify?: boolean;
  userEmail?: string;
  autoDownload?: boolean;
}

const CHART_TYPE_ICONS: Record<ChartType, React.ReactElement> = {
  line: <ShowChart fontSize="small" />,
  bar: <BarChart fontSize="small" />,
  pie: <PieChartIcon fontSize="small" />,
};

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  line: "Line",
  bar: "Bar",
  pie: "Pie",
};

export const QueryDataView = ({
  queryId,
  columns,
  queryMetadata,
  sql,
  defaultView = "grid",
  defaultChartType = "line",
  allowViewSwitch = true,
  allowChartTypeSwitch = true,
  availableChartTypes = ["line", "bar", "pie"],
  chartHeight = 400,
  // Grid props
  useSSE = true,
  paginate = true,
  pageSize = 100,
  performanceWarning = false,
  estimatedRows,
  estimatedSizeGb,
  sortModel,
  onSortModelChange,
  activeColumn,
  onActiveColumnChange,
  activeRows,
  onActiveRowsChange,
  selectionModel,
  onSelectionModelChange,
  showAddColumn,
  onAddColumn,
  onRefsChange,
  notify,
  userEmail,
  autoDownload,
}: QueryDataViewProps) => {
  const [view, setView] = useState<ViewType>(defaultView);
  const [chartType, setChartType] = useState<ChartType>(defaultChartType);

  // Determine suggested chart type from metadata
  // Note: chart metadata may come from different places depending on query source
  const suggestedChartType = useMemo(() => {
    // Check various possible locations for chart suggestion
    const metadata = queryMetadata as any;
    const suggested =
      metadata?.chart?.suggested_chart ||
      metadata?.explanation?.suggested_chart;
    if (suggested && availableChartTypes.includes(suggested as ChartType)) {
      return suggested as ChartType;
    }
    return defaultChartType;
  }, [queryMetadata, availableChartTypes, defaultChartType]);

  // Use suggested type if chart type hasn't been explicitly changed
  const effectiveChartType = chartType || suggestedChartType;

  const handleViewChange = useCallback(
    (_: React.SyntheticEvent, newValue: ViewType) => {
      if (newValue !== null) {
        setView(newValue);
      }
    },
    [],
  );

  const handleChartTypeChange = useCallback(
    (_: React.MouseEvent<HTMLElement>, newType: ChartType | null) => {
      if (newType !== null) {
        setChartType(newType);
      }
    },
    [],
  );

  // Render the active view content
  const renderContent = () => {
    switch (view) {
      case "chart":
        return (
          <QueryChart
            queryId={queryId}
            chartType={effectiveChartType}
            queryMetadata={queryMetadata}
            height={chartHeight}
            showNotifyOption={performanceWarning}
            estimatedRows={estimatedRows}
            estimatedSizeGb={estimatedSizeGb}
          />
        );
      case "sql":
        return (
          <Box sx={{ p: 2, height: "100%", overflow: "auto" }}>
            <HighlightedSQL code={sql || queryMetadata?.sql || ""} />
          </Box>
        );
      case "grid":
      default:
        return (
          <QueryDataGrid
            queryId={queryId}
            columns={columns}
            queryMetadata={queryMetadata}
            useSSE={useSSE}
            paginate={paginate}
            pageSize={pageSize}
            performanceWarning={performanceWarning}
            estimatedRows={estimatedRows}
            estimatedSizeGb={estimatedSizeGb}
            sortModel={sortModel}
            onSortModelChange={onSortModelChange}
            activeColumn={activeColumn}
            onActiveColumnChange={onActiveColumnChange}
            activeRows={activeRows}
            onActiveRowsChange={onActiveRowsChange}
            selectionModel={selectionModel}
            onSelectionModelChange={onSelectionModelChange}
            showAddColumn={showAddColumn}
            onAddColumn={onAddColumn}
            onRefsChange={onRefsChange}
            notify={notify}
            userEmail={userEmail}
            autoDownload={autoDownload}
          />
        );
    }
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header with view tabs and chart type selector */}
      {allowViewSwitch && (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: 1,
            borderColor: "divider",
            px: 1,
          }}
        >
          {/* View tabs */}
          <Tabs value={view} onChange={handleViewChange} sx={{ minHeight: 40 }}>
            <Tab
              value="grid"
              icon={<TableChart fontSize="small" />}
              iconPosition="start"
              label="Grid"
              sx={{ minHeight: 40, py: 0 }}
            />
            <Tab
              value="chart"
              icon={CHART_TYPE_ICONS[effectiveChartType]}
              iconPosition="start"
              label="Chart"
              sx={{ minHeight: 40, py: 0 }}
            />
            {(sql || queryMetadata?.sql) && (
              <Tab
                value="sql"
                icon={<Code fontSize="small" />}
                iconPosition="start"
                label="SQL"
                sx={{ minHeight: 40, py: 0 }}
              />
            )}
          </Tabs>

          {/* Chart type selector (only visible when chart view is active) */}
          {view === "chart" && allowChartTypeSwitch && (
            <ToggleButtonGroup
              value={effectiveChartType}
              exclusive
              onChange={handleChartTypeChange}
              size="small"
              sx={{ mr: 1 }}
            >
              {availableChartTypes.map((type) => (
                <Tooltip key={type} title={CHART_TYPE_LABELS[type]}>
                  <ToggleButton value={type}>
                    {CHART_TYPE_ICONS[type]}
                  </ToggleButton>
                </Tooltip>
              ))}
            </ToggleButtonGroup>
          )}
        </Box>
      )}

      {/* Content area */}
      <Box sx={{ flex: 1, overflow: "hidden" }}>{renderContent()}</Box>
    </Box>
  );
};

export * from "./types";
