import type { GridColDef, GridSortItem } from "@mui/x-data-grid-pro";

import type { TColumn, TQuery } from "@/app/lib/types";

// Refs object exposed for AI context
export interface DataGridRefs {
  cols?: (string | undefined)[]; // [column_name, ...values]
  rows?: (string | any[])[]; // [headers, ...row_values]
}

export interface QueryDataGridProps {
  queryId: string;
  columns: GridColDef[];
  // Query metadata for column descriptions and formatting
  queryMetadata?: TQuery | null;
  useSSE?: boolean; // Default: true
  paginate?: boolean; // Default: true - enables infinite scroll; false = fetch all at once
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
  // NEW COLUMN button
  showAddColumn?: boolean;
  onAddColumn?: () => void;
  // Refs callback - called when selection changes
  onRefsChange?: (refs: DataGridRefs) => void;
  // Notification settings
  notify?: boolean;
  userEmail?: string;
}

export type UIState =
  | "no_cache_no_pending"
  | "no_cache_no_pending_warning"
  | "no_cache_pending"
  | "has_cache_fresh"
  | "has_cache_stale"
  | "has_cache_stale_warning"
  | "error";
