"use client";

import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControlLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid-pro";
import { formatDistanceToNow } from "date-fns";
import { useParams, useRouter } from "next/navigation";
import React, { useCallback, useState } from "react";

import { QueryDataGrid } from "@/app/components/QueryDataGrid";
import { useData } from "@/app/contexts/DataContext";

type SSEEvent = {
  type: string;
  timestamp: string;
  data: any;
};

const StatusChip = ({
  status,
}: {
  status: "idle" | "pending" | "success" | "error";
}) => {
  const colorMap = {
    idle: "default",
    pending: "warning",
    success: "success",
    error: "error",
  } as const;

  return <Chip label={status} color={colorMap[status]} size="small" />;
};

// Generate columns from first row of data
const generateColumns = (rows: any[]): GridColDef[] => {
  if (!rows || rows.length === 0) return [];

  const firstRow = rows[0];
  return Object.keys(firstRow).map((key) => ({
    field: key,
    headerName: key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
    width: 150,
    flex: 1,
  }));
};

const DataTestPage = () => {
  const params = useParams();
  const router = useRouter();
  const queryId = (params?.id as string) || "";

  const [inputQueryId, setInputQueryId] = useState(queryId);
  const [sseEvents, setSSEEvents] = useState<SSEEvent[]>([]);
  const [manualNotify, setManualNotify] = useState(false);
  const [useSSE, setUseSSE] = useState(true);
  const [paginate, setPaginate] = useState(false);
  const [pageSize, setPageSize] = useState(100);
  const [offset, setOffset] = useState(0);
  const [sortBy, setSortBy] = useState("");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  const {
    getQueryState,
    fetchQuery,
    cancelFetch,
    isStale,
    hasCachedData,
    invalidateCache,
    subscribe,
  } = useData();

  const queryState = getQueryState(queryId);
  const stale = isStale(queryId);
  const hasCached = hasCachedData(queryId);

  // Generate columns dynamically from data
  const columns = generateColumns(queryState.rows);

  // Log SSE events
  const logEvent = useCallback((type: string, data: any) => {
    const iso = new Date().toISOString();
    const time = iso.split("T")[1]?.slice(0, 12) ?? iso;
    setSSEEvents((prev) => [
      {
        type,
        timestamp: time,
        data,
      },
      ...prev.slice(0, 49), // Keep last 50 events
    ]);
  }, []);

  const getFetchOptions = (force: boolean = false) => ({
    notify: manualNotify,
    useSSE,
    paginate,
    pageSize,
    offset,
    ...(sortBy ? { sortBy, sortOrder } : {}),
    ...(force ? { force: true } : {}),
  });

  const handleFetch = () => {
    const options = getFetchOptions();
    logEvent("action", {
      action: "fetchQuery",
      queryId,
      ...options,
    });
    fetchQuery(queryId, options);
  };

  const handleForceFetch = () => {
    const options = getFetchOptions(true);
    logEvent("action", {
      action: "fetchQuery",
      queryId,
      ...options,
    });
    fetchQuery(queryId, options);
  };

  const handleCancel = () => {
    logEvent("action", { action: "cancelFetch", queryId });
    cancelFetch(queryId);
  };

  const handleInvalidateCache = () => {
    logEvent("action", { action: "invalidateCache", queryId });
    invalidateCache(queryId);
  };

  const handleSubscribe = () => {
    const options = getFetchOptions();
    logEvent("action", { action: "subscribe", queryId, ...options });

    const unsubscribe = subscribe(queryId, options, {
      onData: (data) => {
        logEvent("data", {
          rows: data.rows.length,
          total_rows: data.total_rows,
        });
      },
      onError: (error) => {
        logEvent("error", { error });
      },
      onCount: (totalRows) => {
        logEvent("count", { totalRows });
      },
      onCancelled: () => {
        logEvent("cancelled", {});
      },
    });

    return unsubscribe;
  };

  const handleNavigate = () => {
    if (inputQueryId && inputQueryId !== queryId) {
      router.push(`/data-test/${inputQueryId}`);
    }
  };

  const clearEvents = () => {
    setSSEEvents([]);
  };

  return (
    <Box sx={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* Left Panel - DataGrid */}
      <Box
        sx={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          borderRight: 1,
          borderColor: "divider",
          overflow: "hidden",
        }}
      >
        {/* Query ID Input */}
        <Box sx={{ p: 2, borderBottom: 1, borderColor: "divider" }}>
          <Stack direction="row" spacing={2} alignItems="center">
            <TextField
              label="Query ID"
              value={inputQueryId}
              onChange={(e) => setInputQueryId(e.target.value)}
              size="small"
              sx={{ flex: 1 }}
            />
            <Button variant="outlined" onClick={handleNavigate}>
              Go
            </Button>
          </Stack>
        </Box>

        {/* DataGrid */}
        <Box sx={{ flex: 1, overflow: "hidden" }}>
          {queryId ? (
            <QueryDataGrid
              queryId={queryId}
              columns={columns}
              performanceWarning={false}
            />
          ) : (
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
              }}
            >
              <Typography color="text.secondary">
                Enter a Query ID to load data
              </Typography>
            </Box>
          )}
        </Box>
      </Box>

      {/* Right Panel - Debug Info */}
      <Box
        sx={{
          width: 450,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          bgcolor: "background.default",
        }}
      >
        <Box sx={{ flex: 1, overflow: "auto", p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Debug Panel
          </Typography>

          {queryId && (
            <>
              {/* Query State */}
              <Card sx={{ mb: 2 }} variant="outlined">
                <CardContent sx={{ py: 1, "&:last-child": { pb: 1 } }}>
                  <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                  >
                    Query State
                  </Typography>
                  <Table size="small">
                    <TableBody>
                      <TableRow>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          Status
                        </TableCell>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          <StatusChip status={queryState.status} />
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          Fetching
                        </TableCell>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          {queryState.isFetching ? "Yes" : "No"}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          Validating
                        </TableCell>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          {queryState.isValidating ? "Yes" : "No"}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell sx={{ py: 0.5, border: 0 }}>Rows</TableCell>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          {queryState.rows.length} / {queryState.totalRows}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          Cached
                        </TableCell>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          {hasCached ? "Yes" : "No"}
                          {stale && hasCached && " (stale)"}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell sx={{ py: 0.5, border: 0 }}>
                          Cached At
                        </TableCell>
                        <TableCell sx={{ py: 0.5, border: 0, fontSize: 11 }}>
                          {queryState.cachedAt
                            ? formatDistanceToNow(queryState.cachedAt, {
                                addSuffix: true,
                              })
                            : "N/A"}
                        </TableCell>
                      </TableRow>
                      {queryState.error && (
                        <TableRow>
                          <TableCell sx={{ py: 0.5, border: 0 }}>
                            Error
                          </TableCell>
                          <TableCell
                            sx={{ py: 0.5, border: 0, color: "error.main" }}
                          >
                            {queryState.error}
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              {/* Actions */}
              <Card sx={{ mb: 2 }} variant="outlined">
                <CardContent sx={{ py: 1, "&:last-child": { pb: 1 } }}>
                  <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                  >
                    Actions
                  </Typography>
                  <Stack spacing={1}>
                    <Stack direction="row" spacing={1}>
                      <Button
                        variant="contained"
                        size="small"
                        onClick={handleFetch}
                        disabled={queryState.isFetching}
                      >
                        Fetch
                      </Button>
                      <Button
                        variant="contained"
                        size="small"
                        color="secondary"
                        onClick={handleForceFetch}
                        disabled={queryState.isFetching}
                      >
                        Force
                      </Button>
                      <Button
                        variant="outlined"
                        size="small"
                        color="error"
                        onClick={handleCancel}
                        disabled={!queryState.isFetching}
                      >
                        Cancel
                      </Button>
                    </Stack>
                    <Stack direction="row" spacing={1}>
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={handleInvalidateCache}
                      >
                        Clear Cache
                      </Button>
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={handleSubscribe}
                        disabled={queryState.isFetching}
                      >
                        Subscribe
                      </Button>
                    </Stack>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <FormControlLabel
                        control={
                          <Switch
                            checked={useSSE}
                            onChange={(e) => setUseSSE(e.target.checked)}
                            size="small"
                          />
                        }
                        label="SSE"
                        sx={{ mr: 2 }}
                      />
                      <FormControlLabel
                        control={
                          <Switch
                            checked={paginate}
                            onChange={(e) => setPaginate(e.target.checked)}
                            size="small"
                          />
                        }
                        label="Paginate"
                      />
                      <FormControlLabel
                        control={
                          <Switch
                            checked={manualNotify}
                            onChange={(e) => setManualNotify(e.target.checked)}
                            size="small"
                          />
                        }
                        label="Notify"
                      />
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>

              {/* Fetch Options */}
              <Card sx={{ mb: 2 }} variant="outlined">
                <CardContent sx={{ py: 1, "&:last-child": { pb: 1 } }}>
                  <Typography
                    variant="subtitle2"
                    color="text.secondary"
                    gutterBottom
                  >
                    Fetch Options
                  </Typography>
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1}>
                      <TextField
                        label="Page Size"
                        type="number"
                        value={pageSize}
                        onChange={(e) =>
                          setPageSize(
                            Math.max(1, parseInt(e.target.value) || 1),
                          )
                        }
                        size="small"
                        sx={{ width: 100 }}
                        inputProps={{ min: 1 }}
                      />
                      <TextField
                        label="Offset"
                        type="number"
                        value={offset}
                        onChange={(e) =>
                          setOffset(Math.max(0, parseInt(e.target.value) || 0))
                        }
                        size="small"
                        sx={{ width: 100 }}
                        inputProps={{ min: 0 }}
                      />
                    </Stack>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <TextField
                        label="Sort By"
                        value={sortBy}
                        onChange={(e) => setSortBy(e.target.value)}
                        size="small"
                        sx={{ flex: 1 }}
                        placeholder="column name"
                      />
                      <Select
                        value={sortOrder}
                        onChange={(e) =>
                          setSortOrder(e.target.value as "asc" | "desc")
                        }
                        size="small"
                        sx={{ width: 80 }}
                        disabled={!sortBy}
                      >
                        <MenuItem value="asc">ASC</MenuItem>
                        <MenuItem value="desc">DESC</MenuItem>
                      </Select>
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>

              {/* SSE Events Log */}
              <Card variant="outlined">
                <CardContent sx={{ py: 1, "&:last-child": { pb: 1 } }}>
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                    mb={1}
                  >
                    <Typography variant="subtitle2" color="text.secondary">
                      SSE Events
                    </Typography>
                    <Button size="small" onClick={clearEvents}>
                      Clear
                    </Button>
                  </Stack>
                  <Paper
                    variant="outlined"
                    sx={{
                      maxHeight: 250,
                      overflow: "auto",
                      bgcolor: "grey.900",
                    }}
                  >
                    {sseEvents.length === 0 ? (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ p: 1, display: "block", fontFamily: "monospace" }}
                      >
                        No events yet
                      </Typography>
                    ) : (
                      <Table size="small">
                        <TableBody>
                          {sseEvents.map((event, idx) => (
                            <TableRow key={idx}>
                              <TableCell
                                sx={{
                                  py: 0.25,
                                  px: 1,
                                  border: 0,
                                  fontFamily: "monospace",
                                  fontSize: 10,
                                  color: "grey.500",
                                  width: 70,
                                }}
                              >
                                {event.timestamp}
                              </TableCell>
                              <TableCell
                                sx={{ py: 0.25, px: 0.5, border: 0, width: 60 }}
                              >
                                <Chip
                                  label={event.type}
                                  size="small"
                                  sx={{ height: 18, fontSize: 10 }}
                                  color={
                                    event.type === "error"
                                      ? "error"
                                      : event.type === "data"
                                        ? "success"
                                        : "default"
                                  }
                                />
                              </TableCell>
                              <TableCell
                                sx={{
                                  py: 0.25,
                                  px: 1,
                                  border: 0,
                                  fontFamily: "monospace",
                                  fontSize: 10,
                                  color: "grey.400",
                                }}
                              >
                                {JSON.stringify(event.data)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </Paper>
                </CardContent>
              </Card>
            </>
          )}
        </Box>
      </Box>
    </Box>
  );
};

export default DataTestPage;
