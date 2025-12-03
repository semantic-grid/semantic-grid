import type { GridColDef, GridSortItem } from "@mui/x-data-grid-pro";

export interface QueryDataGridProps {
  queryId: string;
  sql: string;
  columns: GridColDef[];
  performanceWarning?: boolean;
  estimatedRows?: number;
  estimatedSizeGb?: number;
  sortModel?: GridSortItem[];
  onSortModelChange?: (model: GridSortItem[]) => void;
  // Selection state (managed externally for integration with parent)
  activeColumn?: GridColDef | null;
  onActiveColumnChange?: (column: GridColDef | null) => void;
  activeRows?: any[];
  onActiveRowsChange?: (rows: any[] | undefined) => void;
  selectionModel?: number[];
  onSelectionModelChange?: (selection: number[]) => void;
  // Optional pagination
  pageSize?: number;
}

export type UIState =
  | "no_cache_no_pending"
  | "no_cache_no_pending_warning"
  | "no_cache_pending"
  | "has_cache_fresh"
  | "has_cache_stale"
  | "has_cache_stale_warning"
  | "error";
