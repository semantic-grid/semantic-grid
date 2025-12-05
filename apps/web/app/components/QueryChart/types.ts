import type { GridColDef } from "@mui/x-data-grid-pro";

import type { TQuery } from "@/app/lib/types";

export type ChartType = "line" | "bar" | "pie";

export interface QueryChartProps {
  /** Query ID to fetch/display data for */
  queryId: string;

  /** Chart type to render */
  chartType: ChartType;

  /** Column definitions (optional, can derive from queryMetadata) */
  columns?: GridColDef[];

  /** Query metadata with column info */
  queryMetadata?: TQuery | null;

  /** Chart height in pixels */
  height?: number;

  /** Custom fetch handler (uses DataContext by default) */
  onFetch?: () => void;

  /** Custom fetch with notify handler */
  onFetchWithNotify?: () => void;

  /** Show the "Fetch & Notify" option */
  showNotifyOption?: boolean;

  /** Estimated row count for performance warning */
  estimatedRows?: number;

  /** Estimated size in GB for performance warning */
  estimatedSizeGb?: number;
}
