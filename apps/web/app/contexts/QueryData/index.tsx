"use client";

import {
  ArrowDownward,
  ArrowUpward,
  Edit,
  Insights,
  Link,
  SwapVert,
} from "@mui/icons-material";
import { Box, IconButton, Tooltip } from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid";
import type { GridSortItem } from "@mui/x-data-grid/models/gridSortModel";
import type { ReactElement, RefObject, SyntheticEvent } from "react";
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { StyledValue } from "@/app/components/StyledValue";
import { useInfiniteQuery } from "@/app/hooks/useInfiniteQuery";
import type { TColumn } from "@/app/lib/types";

export const options: Record<
  string,
  { icon: ReactElement; label: string; cta: string }
> = {
  submit: {
    icon: <Edit fontSize="small" />,
    label: "Modify query with",
    cta: "Modify query with",
  },
  new: {
    icon: <Link fontSize="small" />,
    label: "New linked query for",
    cta: "Drill down on",
  },
  analyze: {
    icon: <Insights fontSize="small" />,
    label: "Analyze data of",
    cta: "Analyze data of",
  },
};

export interface QueryDataContextType {
  rows: any[];
  gridColumns: GridColDef[];
  activeColumn: any | null;
  setActiveColumn: React.Dispatch<React.SetStateAction<GridColDef | null>>;
  activeRows: any[] | undefined | null;
  setActiveRows: React.Dispatch<React.SetStateAction<any[] | undefined>>;
  onSelectColumn: (col: GridColDef | null) => void;
  onSelectRow: (rows: any[] | undefined) => void;
  sortModel: GridSortItem[];
  setSortModel: React.Dispatch<React.SetStateAction<GridSortItem[]>>;
  paginationModel: { page: number; pageSize: number };
  setPaginationModel: React.Dispatch<{ page: number; pageSize: number }>;
  rowCount: number;
  isLoading: boolean;
  selectionModel: number[];
  setSelectionModel: React.Dispatch<React.SetStateAction<number[]>>;
  mergedSql: string | undefined;
  isReachingEnd: boolean;
  isValidating: boolean;
  setSize: React.Dispatch<React.SetStateAction<number>>;
  abortController?: AbortController;
}

const canonical = (metadata: any, field: string) =>
  metadata.columns?.find((c: any) => c.id === field || c.column_name === field);

const extractSortModelFromSQL = (
  metadata: any,
  sql: string,
): GridSortItem[] => {
  const match = sql.match(/ORDER\s+BY\s+(.+?)(?:\s+LIMIT|\s+OFFSET|;?\s*$)/i);
  if (!match) return [];

  const clause = match[1];
  if (!clause) return [];

  // @ts-ignore
  return clause
    .split(",")
    .map((part) => part.trim())
    .map((part) => {
      const [field, direction] = part.split(/\s+/);
      if (!field) return undefined; // Skip if no field is specified

      return {
        field: canonical(metadata, field)?.column_name || "",
        sort: direction?.toLowerCase() === "desc" ? "desc" : "asc",
      };
    })
    .filter(Boolean);
};

const signatureSubstrings = ["signature", "hash", "tx", "transaction"];
const walletSubstrings = ["wallet", "address", "account", "mint"];
const tickerSubstrings = ["symbol", "ticker"];

const columnWidth = (name: string) => {
  const isWallet = walletSubstrings.some((sub) => name.includes(sub));
  const isTicker = tickerSubstrings.some((sub) => name.includes(sub));
  const isSignature = signatureSubstrings.some((sub) => name.includes(sub));
  if (isSignature) {
    return 220; // Superwide for tx-related columns
  }
  if (isWallet) {
    return 480; // Wider for wallet-related columns
  }
  if (isTicker) {
    return 180; // Wider for ticker-related columns
  }
  return 200; // Default width for other columns
};

export const Index = createContext<QueryDataContextType | null>(null);

export const QueryDataProvider = ({
  queryId,
  query,
  children,
}: {
  queryId?: string;
  query?: any;
  children: React.ReactNode;
}) => {
  const [activeColumn, setActiveColumn] = useState<GridColDef | null>(null);
  const [activeRows, setActiveRows] = useState<any[]>();

  const [sortModel, setSortModel] = useState<GridSortItem[]>([]);
  const [paginationModel, setPaginationModel] = useState<{
    page: number;
    pageSize: number;
  }>({
    page: 0,
    pageSize: 100,
  });
  const [selectionModel, setSelectionModel] = useState<number[]>([]);
  const mergedSql = useMemo(() => query?.sql, [query]);

  const sortByCol = query?.columns?.find(
    (c: any) =>
      c.id === sortModel[0]?.field || c.column_name === sortModel[0]?.field,
  );
  const sortBy = sortByCol?.column_name;
  const sortOrder = sortModel[0]?.sort || "asc";

  const {
    rows: data,
    totalRows: dataRowCount,
    setSize,
    // isFetchingMore,
    isReachingEnd,
    error: dataError,
    isLoading,
    isValidating,
    abortController,
  } = useInfiniteQuery({
    id: queryId,
    sql: query?.sql,
    sortBy,
    sortOrder,
  });
  console.log("QueryDataProvider data", queryId, data, "error", dataError);
  const hasLoadedOnce = useRef(false);
  const triggered = useRef(false);

  useEffect(() => {
    const ready = !isValidating && !isLoading && !isReachingEnd;

    if (ready && !triggered.current) {
      if (hasLoadedOnce.current) {
        triggered.current = true;
        console.log("revalidate session metadata");
      } else {
        hasLoadedOnce.current = true;
      }
    }

    // Reset `triggered` if list is reloading again
    if (!ready) {
      triggered.current = false;
    }
  }, [isValidating, isLoading, isReachingEnd]);

  const onSortClick = (params: any) => (e: SyntheticEvent) => {
    e.preventDefault(); // prevent default behavior
    // e.stopPropagation(); // prevent triggering other handlers
    const direction =
      sortModel[0]?.field === params.colDef.field &&
      sortModel[0]?.sort !== "asc"
        ? "asc"
        : "desc";

    console.log("set sortModel", params.colDef.field, direction);
    setSortModel([{ field: params.colDef.field, sort: direction }]);
  };

  const gridColumns: GridColDef[] = useMemo(() => {
    const columns = query?.columns;
    const userColumns =
      columns?.map((col: TColumn, idx: number) => ({
        field: col.id || `col_${idx}`,
        headerName: col.column_alias
          ?.replace(/_/g, " ")
          .replace(/^\w/, (c: any) => c.toUpperCase()),
        headerDescription: col.column_description,
        width: col.column_alias ? columnWidth(col.column_alias) : 200,
        sortable: false,
        headerClassName:
          activeColumn?.field === col.column_name
            ? "highlight-column-header"
            : "",
        renderCell: (params: any) => (
          <StyledValue
            columnType={col.column_type?.replace("Nullable(", "")}
            value={params.value}
            params={params}
            successors={[]}
          />
        ),
        renderHeader: (params: any) => (
          <Tooltip
            title={params.colDef.headerDescription || params.colDef.headerName}
          >
            <Box display="flex" alignItems="center">
              <span>{params.colDef.headerName}</span>
              <IconButton size="small" onClick={onSortClick(params)}>
                {sortModel[0] &&
                  col.column_name === sortModel[0].field &&
                  sortModel[0]?.sort === "asc" && <ArrowDownward />}
                {sortModel[0] &&
                  col.column_name === sortModel[0].field &&
                  sortModel[0]?.sort === "desc" && <ArrowUpward />}
                {(!sortModel[0] || col.column_name !== sortModel[0]?.field) && (
                  <SwapVert color="disabled" />
                )}
              </IconButton>
            </Box>
          </Tooltip>
        ),
      })) || [];

    return [...userColumns];
  }, [activeColumn, sortModel, query]);

  const rows = useMemo(
    () =>
      (data || []).map((row: Record<string, any>, idx: number) => ({
        id: idx, // Use index as ID
        ...Object.values(row)
          .slice(0)
          .reduce((acc, val, idx) => {
            const col = gridColumns[idx];
            if (col) {
              acc[col.field] = val || ""; // Map cell to column field
            }
            return acc;
          }, {}),
      })),
    [data, gridColumns],
  );

  const rowCountRef = React.useRef(dataRowCount || query?.row_count || 0);

  const rowCount = React.useMemo(() => {
    if (dataRowCount !== undefined) {
      rowCountRef.current = dataRowCount;
    }
    if (query?.row_count !== undefined) {
      rowCountRef.current = query.row_count;
    }
    return rowCountRef.current;
  }, [dataRowCount]);

  useEffect(() => {
    if (mergedSql) {
      const model = extractSortModelFromSQL(query, mergedSql);
      // console.log("extracted sort model", model);
      setSortModel(model.slice(0, 1)); // Use only the first sort item
    }
  }, [mergedSql]);

  // TODO: remove if not used
  const handleChange = (inputRef: RefObject<HTMLInputElement>) => (e: any) => {
    // console.log("handleChange", e.target.value, inputRef.current);
    if (inputRef.current) {
      // Update value without triggering re-render
      inputRef.current.value = e.target.value;
      // setVal(e.target.value);
    }
  };

  const onSelectRow = (row: any) => {
    setActiveRows(
      // eslint-disable-next-line no-nested-ternary
      row ? (activeRows ? [...activeRows, row] : [row]) : undefined,
    );
    setActiveColumn(null); // Clear active column on row selection
    if (!row) {
      setSelectionModel([]);
    }
    setSelectionModel((rr) => (row ? [...rr, row.id] : [...rr])); // Set selection model to the selected row
  };

  const onSelectColumn = (col: any) => {
    setActiveColumn(col);
  };

  return (
    <Index.Provider
      value={{
        rows,
        gridColumns,
        activeColumn,
        setActiveColumn,
        activeRows,
        setActiveRows,
        onSelectRow,
        onSelectColumn,
        sortModel,
        setSortModel,
        paginationModel,
        setPaginationModel,
        rowCount,
        isLoading,
        selectionModel,
        setSelectionModel,
        mergedSql,
        isReachingEnd,
        isValidating,
        setSize,
        abortController,
      }}
    >
      {children}
    </Index.Provider>
  );
};

export const useQueryData = (): QueryDataContextType => {
  const ctx = useContext(Index);
  if (!ctx)
    throw new Error("useQueryData must be used within a QueryDataProvider");
  return ctx;
};
