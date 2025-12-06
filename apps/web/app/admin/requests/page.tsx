"use client";

import { withPageAuthRequired } from "@auth0/nextjs-auth0/client";
import { Close, Search } from "@mui/icons-material";
import {
  Box,
  Button,
  Checkbox,
  Drawer,
  FormControl,
  FormControlLabel,
  FormGroup,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Rating,
  Select,
  TextField,
  Typography,
} from "@mui/material";
import type { GridColDef, GridRowParams } from "@mui/x-data-grid-pro";
import {
  DataGridPro as DataGrid,
  GridFooterContainer,
  GridPagination,
  useGridApiContext,
} from "@mui/x-data-grid-pro";
import { saveAs } from "file-saver";
import { useCallback, useMemo, useState } from "react";
import * as React from "react";

import type { components } from "@/app/api/apegpt/types.gen";
import HighlightedSQL from "@/app/components/SqlView";
import { useAdminRequests } from "@/app/hooks/useAdminRequests";

type GetRequestModel = components["schemas"]["GetRequestModel"];

const ROWS_PER_PAGE = 50;

function exportRowsAsCSV(rows: any[]) {
  if (rows.length === 0) return;

  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(","),
    ...rows.map((row) =>
      headers.map((field) => JSON.stringify(row[field] ?? "")).join(","),
    ),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  saveAs(blob, "selected-rows.csv");
}

const CustomFooter = () => {
  const apiRef = useGridApiContext();

  const handleExport = () => {
    const selectedIDs = apiRef.current.getSelectedRows();
    const selectedRows = Array.from(selectedIDs.values());
    exportRowsAsCSV(selectedRows);
  };

  return (
    <GridFooterContainer>
      <Button onClick={handleExport} variant="outlined" sx={{ m: 1 }}>
        Export Selected to CSV
      </Button>
      <Box sx={{ flex: 1 }} />
      <GridPagination />
    </GridFooterContainer>
  );
};

const RequestDetailDrawer = ({
  request,
  open,
  onClose,
}: {
  request: GetRequestModel | null;
  open: boolean;
  onClose: () => void;
}) => {
  if (!request) return null;

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: { width: { xs: "100%", sm: "600px", md: "800px" }, p: 3 },
      }}
    >
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          mb: 3,
        }}
      >
        <Typography variant="h6">Request Details</Typography>
        <IconButton onClick={onClose}>
          <Close />
        </IconButton>
      </Box>

      <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {/* User & Date */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            User
          </Typography>
          <Typography variant="body1">
            {request.session?.user || "Unknown"}
          </Typography>
        </Box>

        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            Date
          </Typography>
          <Typography variant="body1">
            {new Date(request.created_at).toLocaleString()}
          </Typography>
        </Box>

        {/* Rating */}
        {request.rating !== null && request.rating !== undefined && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Rating
            </Typography>
            <Rating value={request.rating} max={10} precision={1} readOnly />
          </Box>
        )}

        {/* Review */}
        {request.review && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Review
            </Typography>
            <Typography variant="body1">{request.review}</Typography>
          </Box>
        )}

        {/* Request */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            Request
          </Typography>
          <Typography
            variant="body1"
            sx={{
              whiteSpace: "pre-wrap",
              backgroundColor: "action.hover",
              p: 2,
              borderRadius: 1,
            }}
          >
            {request.request}
          </Typography>
        </Box>

        {/* SQL */}
        {request.sql && (
          <Box>
            <Typography
              variant="subtitle2"
              color="text.secondary"
              sx={{ mb: 1 }}
            >
              SQL
            </Typography>
            <Box
              sx={{
                maxHeight: "300px",
                overflow: "auto",
                backgroundColor: "grey.900",
                borderRadius: 1,
              }}
            >
              <HighlightedSQL code={request.sql} />
            </Box>
          </Box>
        )}

        {/* Intent */}
        {request.intent && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Intent
            </Typography>
            <Typography variant="body1">{request.intent}</Typography>
          </Box>
        )}

        {/* Error */}
        {request.err && (
          <Box>
            <Typography variant="subtitle2" color="error">
              Error
            </Typography>
            <Typography
              variant="body1"
              sx={{
                color: "error.main",
                whiteSpace: "pre-wrap",
                backgroundColor: "error.light",
                p: 2,
                borderRadius: 1,
              }}
            >
              {request.err}
            </Typography>
          </Box>
        )}

        {/* Session & Request IDs */}
        <Box
          sx={{ mt: 2, pt: 2, borderTop: "1px solid", borderColor: "divider" }}
        >
          <Typography variant="caption" color="text.secondary" display="block">
            Session ID: {request.session_id}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Request ID: {request.request_id}
          </Typography>
        </Box>
      </Box>
    </Drawer>
  );
};

const REQUEST_STATUSES = [
  "Done",
  "New",
  "Intent",
  "SQL",
  "DataFetch",
  "Retry",
  "Finalizing",
  "InProgress",
  "Scheduled",
  "Error",
  "Cancelled",
];

const Page = withPageAuthRequired(
  () => {
    const [paginationModel, setPaginationModel] = useState({
      pageSize: ROWS_PER_PAGE,
      page: 0,
    });
    const [searchInput, setSearchInput] = useState("");
    const [search, setSearch] = useState("");
    const [status, setStatus] = useState("Done");
    const [hasFeedback, setHasFeedback] = useState(false);
    const [selectedRequest, setSelectedRequest] =
      useState<GetRequestModel | null>(null);
    const [drawerOpen, setDrawerOpen] = useState(false);

    const { data, total, isLoading } = useAdminRequests(
      paginationModel.pageSize,
      paginationModel.page * paginationModel.pageSize,
      status,
      search || undefined,
      hasFeedback,
    );

    const handleSearch = useCallback(() => {
      setSearch(searchInput);
      setPaginationModel((prev) => ({ ...prev, page: 0 }));
    }, [searchInput]);

    const handleSearchKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
          handleSearch();
        }
      },
      [handleSearch],
    );

    const handleRowClick = useCallback((params: GridRowParams) => {
      setSelectedRequest(params.row as GetRequestModel);
      setDrawerOpen(true);
    }, []);

    const handleCloseDrawer = useCallback(() => {
      setDrawerOpen(false);
    }, []);

    const columns = useMemo<GridColDef<GetRequestModel>[]>(
      () => [
        {
          field: "created_at",
          headerName: "Date",
          width: 180,
          sortable: true,
          renderCell: (params) =>
            new Date(params.value as string).toLocaleString(),
        },
        {
          field: "user",
          headerName: "User",
          width: 250,
          sortable: true,
          renderCell: (params) => params.row.session?.user || "Unknown",
        },
        {
          field: "request",
          headerName: "Request",
          flex: 1,
          minWidth: 300,
          sortable: true,
        },
        {
          field: "sql",
          headerName: "SQL",
          width: 300,
          sortable: false,
          renderCell: (params) => (
            <Box
              sx={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                fontFamily: "monospace",
                fontSize: "0.75rem",
              }}
            >
              {params.value}
            </Box>
          ),
        },
        {
          field: "rating",
          headerName: "Rating",
          width: 150,
          sortable: true,
          renderCell: (params) =>
            params.value != null ? (
              <Rating
                size="small"
                value={params.value}
                max={10}
                precision={1}
                readOnly
              />
            ) : null,
        },
        {
          field: "status",
          headerName: "Status",
          width: 100,
          sortable: true,
        },
      ],
      [],
    );

    const rows = useMemo(
      () =>
        (data || []).map((r: GetRequestModel) => ({
          ...r,
          id: `${r.session_id}_${r.request_id}`,
        })),
      [data],
    );

    return (
      <Box
        sx={{
          height: "100vh",
          width: "100%",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header with search */}
        <Box
          sx={{
            p: 2,
            display: "flex",
            alignItems: "center",
            gap: 2,
            borderBottom: "1px solid",
            borderColor: "divider",
          }}
        >
          <Typography variant="h5" sx={{ fontWeight: 600 }}>
            Admin Requests
          </Typography>
          <Box sx={{ flex: 1 }} />
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Status</InputLabel>
            <Select
              value={status}
              label="Status"
              onChange={(e) => {
                setStatus(e.target.value);
                setPaginationModel((prev) => ({ ...prev, page: 0 }));
              }}
            >
              {REQUEST_STATUSES.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormGroup>
            <FormControlLabel
              control={
                <Checkbox
                  checked={hasFeedback}
                  onChange={(e) => {
                    setHasFeedback(e.target.checked);
                    setPaginationModel((prev) => ({ ...prev, page: 0 }));
                  }}
                />
              }
              label="Has feedback"
              sx={{ color: "text.primary" }}
            />
          </FormGroup>
          <TextField
            size="small"
            placeholder="Search requests, SQL, or users..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            sx={{ width: 350 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search />
                </InputAdornment>
              ),
              endAdornment: searchInput ? (
                <InputAdornment position="end">
                  <IconButton
                    size="small"
                    onClick={() => {
                      setSearchInput("");
                      setSearch("");
                      setPaginationModel((prev) => ({ ...prev, page: 0 }));
                    }}
                  >
                    <Close fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : null,
            }}
          />
          <Button variant="contained" onClick={handleSearch}>
            Search
          </Button>
        </Box>

        {/* DataGrid */}
        <Box sx={{ flex: 1, width: "100%" }}>
          <DataGrid
            loading={isLoading}
            rows={rows}
            columns={columns}
            density="compact"
            checkboxSelection
            pageSizeOptions={[25, 50, 100]}
            slots={{
              footer: CustomFooter,
            }}
            paginationModel={paginationModel}
            paginationMode="server"
            onPaginationModelChange={setPaginationModel}
            rowCount={total}
            onRowClick={handleRowClick}
            sx={{
              border: "none",
              "& .MuiDataGrid-row": {
                cursor: "pointer",
              },
              "& .MuiDataGrid-row:hover": {
                backgroundColor: "action.hover",
              },
            }}
          />
        </Box>

        {/* Detail Drawer */}
        <RequestDetailDrawer
          request={selectedRequest}
          open={drawerOpen}
          onClose={handleCloseDrawer}
        />
      </Box>
    );
  },
  { returnTo: "/admin/requests" },
);

export default Page;
