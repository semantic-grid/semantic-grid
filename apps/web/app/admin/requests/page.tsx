"use client";

import { withPageAuthRequired } from "@auth0/nextjs-auth0/client";
import {
  Check,
  Close,
  ExpandLess,
  ExpandMore,
  Search,
} from "@mui/icons-material";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
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
  Switch,
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
import {
  fetchPromptVersion,
  type GetPromptVersionModel,
  type GetTraceStepModel,
  updateAdminRequest,
  useAdminRequests,
  useRequestTrace,
} from "@/app/hooks/useAdminRequests";

type GetRequestModel = components["schemas"]["GetRequestModel"];
type GetDataFetchModel = components["schemas"]["GetDataFetchModel"];

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

// Step type colors for visual distinction
const STEP_TYPE_COLORS: Record<
  string,
  "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning"
> = {
  request_context: "default",
  prompt_assembly: "info",
  llm_call: "primary",
  validation: "success",
  repair: "warning",
  error: "error",
  mcp_call: "secondary",
  sql_execution: "success",
};

// Data fetch status colors
const DATA_FETCH_STATUS_COLORS: Record<
  string,
  "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning"
> = {
  pending: "default",
  running: "info",
  success: "success",
  error: "error",
  cancelled: "warning",
  timed_out: "error",
};

// Format duration in human-readable form
const formatDuration = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

// Format token count with comma separators
const formatTokens = (count: number | null | undefined): string => {
  if (count === null || count === undefined) return "-";
  return count.toLocaleString();
};

// Trace Step Row Component
const TraceStepRow = ({
  step,
  onViewPrompt,
}: {
  step: GetTraceStepModel;
  onViewPrompt: (versionId: string) => void;
}) => {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = step.metadata || step.output_parsed || step.error;

  return (
    <Box sx={{ borderBottom: "1px solid", borderColor: "divider" }}>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          py: 1,
          px: 1,
          cursor: hasDetails ? "pointer" : "default",
          "&:hover": hasDetails ? { backgroundColor: "action.hover" } : {},
        }}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <Typography
          variant="caption"
          sx={{ width: 24, color: "text.secondary" }}
        >
          {step.step_number}
        </Typography>
        <Chip
          label={step.step_type}
          size="small"
          color={STEP_TYPE_COLORS[step.step_type] || "default"}
          variant="outlined"
          sx={{ minWidth: 120 }}
        />
        {step.model && (
          <Chip label={step.model} size="small" variant="outlined" />
        )}
        {(step.tokens_in || step.tokens_out) && (
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            {formatTokens(step.tokens_in)} in / {formatTokens(step.tokens_out)}{" "}
            out
          </Typography>
        )}
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {formatDuration(step.duration_ms)}
        </Typography>
        {step.prompt_version_ids && step.prompt_version_ids.length > 0 && (
          <Button
            size="small"
            variant="text"
            onClick={(e) => {
              e.stopPropagation();
              const versionId = step.prompt_version_ids?.[0];
              if (versionId) onViewPrompt(versionId);
            }}
          >
            View Prompt
          </Button>
        )}
        {hasDetails && (
          <IconButton size="small">
            {expanded ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        )}
      </Box>
      <Collapse in={expanded}>
        <Box sx={{ pl: 5, pr: 2, pb: 2 }}>
          {step.error && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="error" fontWeight={600}>
                Error:
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  color: "error.main",
                  whiteSpace: "pre-wrap",
                  fontFamily: "monospace",
                  fontSize: "0.75rem",
                }}
              >
                {step.error}
              </Typography>
            </Box>
          )}
          {step.output_parsed && (
            <Box sx={{ mb: 1 }}>
              <Typography
                variant="caption"
                color="text.secondary"
                fontWeight={600}
              >
                Output:
              </Typography>
              <Box
                component="pre"
                sx={{
                  backgroundColor: "background.default",
                  border: "1px solid",
                  borderColor: "divider",
                  p: 1,
                  borderRadius: 1,
                  overflow: "auto",
                  maxHeight: 200,
                  fontSize: "0.7rem",
                }}
              >
                {JSON.stringify(step.output_parsed, null, 2)}
              </Box>
            </Box>
          )}
          {step.metadata && (
            <Box>
              <Typography
                variant="caption"
                color="text.secondary"
                fontWeight={600}
              >
                Metadata:
              </Typography>
              <Box
                component="pre"
                sx={{
                  backgroundColor: "background.default",
                  border: "1px solid",
                  borderColor: "divider",
                  p: 1,
                  borderRadius: 1,
                  overflow: "auto",
                  maxHeight: 150,
                  fontSize: "0.7rem",
                }}
              >
                {JSON.stringify(step.metadata, null, 2)}
              </Box>
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  );
};

// Trace Section Component
const TraceSection = ({ requestId }: { requestId: string }) => {
  const { trace, isLoading, error } = useRequestTrace(requestId);
  const [expanded, setExpanded] = useState(true);
  const [promptDialogOpen, setPromptDialogOpen] = useState(false);
  const [promptContent, setPromptContent] =
    useState<GetPromptVersionModel | null>(null);
  const [loadingPrompt, setLoadingPrompt] = useState(false);

  const handleViewPrompt = async (versionId: string) => {
    setLoadingPrompt(true);
    try {
      const version = await fetchPromptVersion(versionId);
      setPromptContent(version);
      setPromptDialogOpen(true);
    } catch (err) {
      console.error("Failed to fetch prompt:", err);
    } finally {
      setLoadingPrompt(false);
    }
  };

  if (isLoading) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, py: 2 }}>
        <CircularProgress size={16} />
        <Typography variant="body2" color="text.secondary">
          Loading trace...
        </Typography>
      </Box>
    );
  }

  if (error || !trace) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        No trace available
      </Typography>
    );
  }

  return (
    <>
      <Box
        sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1 }}
      >
        {/* Summary Header */}
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 2,
            p: 1.5,
            backgroundColor: "action.hover",
            cursor: "pointer",
          }}
          onClick={() => setExpanded(!expanded)}
        >
          <Typography variant="subtitle2" fontWeight={600}>
            Trace ({trace.summary?.total_steps || 0} steps)
          </Typography>
          <Box sx={{ display: "flex", gap: 1, flex: 1, flexWrap: "wrap" }}>
            {trace.summary?.llm_calls > 0 && (
              <Chip
                label={`${trace.summary.llm_calls} LLM calls`}
                size="small"
                color="primary"
                variant="outlined"
              />
            )}
            {trace.summary?.total_tokens_in > 0 && (
              <Chip
                label={`${formatTokens(trace.summary.total_tokens_in)} tokens in`}
                size="small"
                variant="outlined"
              />
            )}
            {trace.summary?.total_tokens_out > 0 && (
              <Chip
                label={`${formatTokens(trace.summary.total_tokens_out)} tokens out`}
                size="small"
                variant="outlined"
              />
            )}
            {trace.summary?.repairs > 0 && (
              <Chip
                label={`${trace.summary.repairs} repairs`}
                size="small"
                color="warning"
                variant="outlined"
              />
            )}
            {trace.summary?.has_errors && (
              <Chip
                label="Has errors"
                size="small"
                color="error"
                variant="outlined"
              />
            )}
          </Box>
          <Typography variant="caption" color="text.secondary">
            {formatDuration(trace.summary?.total_duration_ms)}
          </Typography>
          <IconButton size="small">
            {expanded ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        </Box>

        {/* Steps */}
        <Collapse in={expanded}>
          <Box sx={{ maxHeight: 400, overflow: "auto" }}>
            {trace.steps?.map((step) => (
              <TraceStepRow
                key={step.id}
                step={step}
                onViewPrompt={handleViewPrompt}
              />
            ))}
          </Box>
        </Collapse>
      </Box>

      {/* Prompt Content Dialog */}
      <Dialog
        open={promptDialogOpen}
        onClose={() => setPromptDialogOpen(false)}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle>
          Prompt Content
          <IconButton
            onClick={() => setPromptDialogOpen(false)}
            sx={{ position: "absolute", right: 8, top: 8 }}
          >
            <Close />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          {loadingPrompt && <CircularProgress />}
          {!loadingPrompt && promptContent && (
            <Box>
              <Box sx={{ mb: 2, display: "flex", gap: 2, flexWrap: "wrap" }}>
                <Chip
                  label={promptContent.prompt_item_type || "Unknown type"}
                  size="small"
                  variant="outlined"
                />
                <Typography variant="caption" color="text.secondary">
                  Hash: {promptContent.content_hash?.slice(0, 16)}...
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Created: {new Date(promptContent.created_at).toLocaleString()}
                </Typography>
              </Box>
              <Box
                component="pre"
                sx={{
                  backgroundColor: "background.default",
                  border: "1px solid",
                  borderColor: "divider",
                  p: 2,
                  borderRadius: 1,
                  overflow: "auto",
                  maxHeight: "60vh",
                  fontSize: "0.8rem",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {promptContent.content}
              </Box>
            </Box>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
};

// Individual Data Fetch Row
const DataFetchRow = ({
  dataFetch,
  index,
}: {
  dataFetch: GetDataFetchModel;
  index: number;
}) => {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = dataFetch.error || dataFetch.query_params;

  return (
    <Box sx={{ borderBottom: "1px solid", borderColor: "divider" }}>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          py: 1,
          px: 1,
          cursor: hasDetails ? "pointer" : "default",
          "&:hover": hasDetails ? { backgroundColor: "action.hover" } : {},
        }}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <Typography
          variant="caption"
          sx={{ width: 24, color: "text.secondary" }}
        >
          {index + 1}
        </Typography>
        <Chip
          label={dataFetch.status}
          size="small"
          color={DATA_FETCH_STATUS_COLORS[dataFetch.status] || "default"}
          variant="outlined"
          sx={{ minWidth: 80 }}
        />
        {dataFetch.cache_hit && (
          <Chip
            label="Cache"
            size="small"
            color="info"
            variant="outlined"
            sx={{ height: 20, fontSize: "0.65rem" }}
          />
        )}
        {dataFetch.row_count !== null && dataFetch.row_count !== undefined && (
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            {formatTokens(dataFetch.row_count)} rows
          </Typography>
        )}
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {formatDuration(dataFetch.duration_ms)}
        </Typography>
        <Typography
          variant="caption"
          sx={{ color: "text.secondary", fontSize: "0.65rem" }}
        >
          {new Date(dataFetch.created_at).toLocaleTimeString()}
        </Typography>
        {hasDetails && (
          <IconButton size="small">
            {expanded ? <ExpandLess /> : <ExpandMore />}
          </IconButton>
        )}
      </Box>
      <Collapse in={expanded}>
        <Box sx={{ pl: 5, pr: 2, pb: 2 }}>
          {dataFetch.error && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="error" fontWeight={600}>
                Error:
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  color: "error.main",
                  whiteSpace: "pre-wrap",
                  fontFamily: "monospace",
                  fontSize: "0.75rem",
                }}
              >
                {dataFetch.error}
              </Typography>
            </Box>
          )}
          {dataFetch.query_params && (
            <Box sx={{ mb: 1 }}>
              <Typography
                variant="caption"
                color="text.secondary"
                fontWeight={600}
              >
                Query Params:
              </Typography>
              <Box
                component="pre"
                sx={{
                  backgroundColor: "background.default",
                  border: "1px solid",
                  borderColor: "divider",
                  p: 1,
                  borderRadius: 1,
                  overflow: "auto",
                  maxHeight: 100,
                  fontSize: "0.7rem",
                }}
              >
                {JSON.stringify(dataFetch.query_params, null, 2)}
              </Box>
            </Box>
          )}
          <Box
            sx={{
              display: "flex",
              gap: 2,
              flexWrap: "wrap",
              mt: 1,
            }}
          >
            {dataFetch.started_at && (
              <Typography variant="caption" color="text.secondary">
                Started: {new Date(dataFetch.started_at).toLocaleString()}
              </Typography>
            )}
            {dataFetch.completed_at && (
              <Typography variant="caption" color="text.secondary">
                Completed: {new Date(dataFetch.completed_at).toLocaleString()}
              </Typography>
            )}
            <Typography variant="caption" color="text.secondary">
              Requestor: {dataFetch.requestor}
            </Typography>
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
};

// Data Fetches Section Component
const DataFetchesSection = ({
  dataFetches,
}: {
  dataFetches: GetDataFetchModel[] | null | undefined;
}) => {
  const [expanded, setExpanded] = useState(true);

  if (!dataFetches || dataFetches.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        No data fetches recorded
      </Typography>
    );
  }

  // Calculate summary stats
  const totalFetches = dataFetches.length;
  const successfulFetches = dataFetches.filter(
    (df) => df.status === "success",
  ).length;
  const cacheHits = dataFetches.filter((df) => df.cache_hit).length;
  const totalDuration = dataFetches.reduce(
    (acc, df) => acc + (df.duration_ms || 0),
    0,
  );
  const totalRows = dataFetches.reduce(
    (acc, df) => acc + (df.row_count || 0),
    0,
  );
  const hasErrors = dataFetches.some(
    (df) => df.status === "error" || df.status === "timed_out",
  );

  return (
    <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
      {/* Summary Header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          p: 1.5,
          backgroundColor: "action.hover",
          cursor: "pointer",
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Typography variant="subtitle2" fontWeight={600}>
          Data Fetches ({totalFetches})
        </Typography>
        <Box sx={{ display: "flex", gap: 1, flex: 1, flexWrap: "wrap" }}>
          {successfulFetches > 0 && (
            <Chip
              label={`${successfulFetches} successful`}
              size="small"
              color="success"
              variant="outlined"
            />
          )}
          {cacheHits > 0 && (
            <Chip
              label={`${cacheHits} cache hits`}
              size="small"
              color="info"
              variant="outlined"
            />
          )}
          {totalRows > 0 && (
            <Chip
              label={`${formatTokens(totalRows)} rows`}
              size="small"
              variant="outlined"
            />
          )}
          {hasErrors && (
            <Chip
              label="Has errors"
              size="small"
              color="error"
              variant="outlined"
            />
          )}
        </Box>
        <Typography variant="caption" color="text.secondary">
          {formatDuration(totalDuration)}
        </Typography>
        <IconButton size="small">
          {expanded ? <ExpandLess /> : <ExpandMore />}
        </IconButton>
      </Box>

      {/* Data Fetch Rows */}
      <Collapse in={expanded}>
        <Box sx={{ maxHeight: 300, overflow: "auto" }}>
          {dataFetches.map((df, index) => (
            <DataFetchRow key={df.id} dataFetch={df} index={index} />
          ))}
        </Box>
      </Collapse>
    </Box>
  );
};

const RequestDetailDrawer = ({
  request,
  open,
  onClose,
  onUpdate,
}: {
  request: GetRequestModel | null;
  open: boolean;
  onClose: () => void;
  onUpdate: () => void;
}) => {
  const [isTest, setIsTest] = useState(false);
  const [isFixed, setIsFixed] = useState(false);
  const [needsFixing, setNeedsFixing] = useState(false);
  const [fixComment, setFixComment] = useState("");
  const [saving, setSaving] = useState(false);

  // Sync local state when request changes
  React.useEffect(() => {
    if (request) {
      setIsTest(request.is_test ?? false);
      setIsFixed(request.is_fixed ?? false);
      // needs_fixing may not be in generated types yet - use type assertion
      setNeedsFixing((request as any).needs_fixing ?? false);
      setFixComment(request.fix_comment ?? "");
    }
  }, [request]);

  const handleSave = async () => {
    if (!request) return;
    setSaving(true);
    try {
      await updateAdminRequest(request.request_id, {
        is_test: isTest,
        is_fixed: isFixed,
        needs_fixing: needsFixing,
        fix_comment: fixComment || undefined,
      });
      onUpdate();
      onClose();
    } catch (err) {
      console.error("Failed to save:", err);
    } finally {
      setSaving(false);
    }
  };

  if (!request) return null;

  const hasChanges =
    isTest !== (request.is_test ?? false) ||
    isFixed !== (request.is_fixed ?? false) ||
    needsFixing !== ((request as any).needs_fixing ?? false) ||
    fixComment !== (request.fix_comment ?? "");

  // Check if this is an "Approved - proceed with SQL generation" request
  const isApprovalRequest = request.request?.startsWith(
    "Approved - proceed with SQL generation",
  );

  // Display text: use intent for approval requests, otherwise original request
  const displayRequest = isApprovalRequest
    ? request.intent || request.request
    : request.request;

  // Show intent field only for original requests (not approval requests) that have intent
  const showIntent = !isApprovalRequest && request.intent;

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: "100%", sm: "600px", md: "800px" },
          p: 3,
          display: "flex",
          flexDirection: "column",
        },
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

      <Box sx={{ display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
        {/* Admin Controls */}
        <Box
          sx={{
            p: 2,
            borderRadius: 1,
            backgroundColor: "action.hover",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <Typography variant="subtitle2" fontWeight={600}>
            Admin Controls
          </Typography>
          <Box sx={{ display: "flex", gap: 3 }}>
            <FormControlLabel
              control={
                <Switch
                  checked={isTest}
                  onChange={(e) => setIsTest(e.target.checked)}
                />
              }
              label="Is Test"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={needsFixing}
                  onChange={(e) => setNeedsFixing(e.target.checked)}
                />
              }
              label="Needs Fixing"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={isFixed}
                  onChange={(e) => setIsFixed(e.target.checked)}
                />
              }
              label="Is Fixed"
            />
          </Box>
          <TextField
            label="Fix Comment"
            multiline
            rows={2}
            value={fixComment}
            onChange={(e) => setFixComment(e.target.value)}
            size="small"
            fullWidth
          />
          {request.fixed_by && (
            <Typography variant="caption" color="text.secondary">
              Fixed by: {request.fixed_by}
              {request.fixed_ts &&
                ` on ${new Date(request.fixed_ts).toLocaleString()}`}
            </Typography>
          )}
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={!hasChanges || saving}
            sx={{ alignSelf: "flex-start" }}
          >
            {saving ? "Saving..." : "Save Changes"}
          </Button>
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
            {displayRequest}
          </Typography>
        </Box>

        {/* Intent - only for original requests */}
        {showIntent && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Intent
            </Typography>
            <Typography variant="body1">{request.intent}</Typography>
          </Box>
        )}

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
                backgroundColor: "background.default",
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 1,
              }}
            >
              <HighlightedSQL code={request.sql} />
            </Box>
            <Button
              variant="outlined"
              size="small"
              sx={{ mt: 1 }}
              disabled={!request.query?.query_id}
              onClick={() =>
                window.open(`/q/${request.query?.query_id}`, "_blank")
              }
            >
              Run Query
            </Button>
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
                backgroundColor: "action.hover",
                p: 2,
                borderRadius: 1,
              }}
            >
              {request.err}
            </Typography>
          </Box>
        )}

        {/* Execution Trace */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Execution Trace
          </Typography>
          <TraceSection requestId={request.request_id} />
        </Box>

        {/* Data Fetches */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Data Fetches
          </Typography>
          <DataFetchesSection dataFetches={request.data_fetches} />
        </Box>
      </Box>

      {/* Footer with User, IDs, and Date */}
      <Box
        sx={{
          mt: 3,
          pt: 2,
          borderTop: "1px solid",
          borderColor: "divider",
          display: "flex",
          flexDirection: "column",
          gap: 0.5,
        }}
      >
        <Typography variant="caption" color="text.secondary">
          User: {request.session?.user || "Unknown"}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Session: {request.session_id}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Request: {request.request_id}
        </Typography>
        {request.query?.query_id && (
          <Typography variant="caption" color="text.secondary">
            Query: {request.query.query_id}
          </Typography>
        )}
        <Typography variant="caption" color="text.secondary">
          Date: {new Date(request.created_at).toLocaleString()}
        </Typography>
      </Box>
    </Drawer>
  );
};

const REQUEST_STATUSES = [
  "All",
  "Done",
  "New",
  "Intent",
  "Planning",
  "FeedbackRequested",
  "SQL",
  "DataFetch",
  "Retry",
  "Finalizing",
  "InProgress",
  "Scheduled",
  "Error",
  "Cancelled",
];

// Filter options for is_test and is_fixed
const BOOL_FILTER_OPTIONS = [
  { value: "all", label: "All" },
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
];

const Page = withPageAuthRequired(
  () => {
    const [paginationModel, setPaginationModel] = useState({
      pageSize: ROWS_PER_PAGE,
      page: 0,
    });
    const [searchInput, setSearchInput] = useState("");
    const [search, setSearch] = useState("");
    const [status, setStatus] = useState("All");
    const [hasFeedback, setHasFeedback] = useState(false);
    const [isTestFilter, setIsTestFilter] = useState<string>("all");
    const [isFixedFilter, setIsFixedFilter] = useState<string>("all");
    const [needsFixingFilter, setNeedsFixingFilter] = useState<string>("all");
    const [selectedRequest, setSelectedRequest] =
      useState<GetRequestModel | null>(null);
    const [drawerOpen, setDrawerOpen] = useState(false);

    // Convert filter string to boolean | undefined
    const isTestValue =
      isTestFilter === "all" ? undefined : isTestFilter === "true";
    const isFixedValue =
      isFixedFilter === "all" ? undefined : isFixedFilter === "true";
    const needsFixingValue =
      needsFixingFilter === "all" ? undefined : needsFixingFilter === "true";

    const { data, total, isLoading, mutate } = useAdminRequests(
      paginationModel.pageSize,
      paginationModel.page * paginationModel.pageSize,
      status === "All" ? undefined : status,
      search || undefined,
      hasFeedback,
      isTestValue,
      isFixedValue,
      needsFixingValue,
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
          minWidth: 200,
          sortable: true,
          renderCell: (params) => {
            const request = params.value as string;
            const isApproval = request?.startsWith(
              "Approved - proceed with SQL generation",
            );
            return isApproval ? params.row.intent || request : request;
          },
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
          field: "is_test",
          headerName: "Test",
          width: 60,
          sortable: true,
          renderCell: (params) => (params.value ? <Check /> : null),
        },
        {
          field: "needs_fixing",
          headerName: "To Fix",
          width: 60,
          sortable: true,
          renderCell: (params) =>
            (params.row as any).needs_fixing ? <Check /> : null,
        },
        {
          field: "is_fixed",
          headerName: "Fixed",
          width: 60,
          sortable: true,
          renderCell: (params) => (params.value ? <Check /> : null),
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
          <FormControl size="small" sx={{ minWidth: 100 }}>
            <InputLabel>Test</InputLabel>
            <Select
              value={isTestFilter}
              label="Test"
              onChange={(e) => {
                setIsTestFilter(e.target.value);
                setPaginationModel((prev) => ({ ...prev, page: 0 }));
              }}
            >
              {BOOL_FILTER_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 100 }}>
            <InputLabel>Fixed</InputLabel>
            <Select
              value={isFixedFilter}
              label="Fixed"
              onChange={(e) => {
                setIsFixedFilter(e.target.value);
                setPaginationModel((prev) => ({ ...prev, page: 0 }));
              }}
            >
              {BOOL_FILTER_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Needs Fixing</InputLabel>
            <Select
              value={needsFixingFilter}
              label="Needs Fixing"
              onChange={(e) => {
                setNeedsFixingFilter(e.target.value);
                setPaginationModel((prev) => ({ ...prev, page: 0 }));
              }}
            >
              {BOOL_FILTER_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
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
        <Box sx={{ flex: 1, width: "100%", minHeight: 0 }}>
          <DataGrid
            loading={isLoading}
            rows={rows}
            columns={columns}
            density="compact"
            checkboxSelection
            disableRowSelectionOnClick
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
              height: "100%",
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
          onUpdate={() => mutate()}
        />
      </Box>
    );
  },
  { returnTo: "/admin/requests" },
);

export default Page;
