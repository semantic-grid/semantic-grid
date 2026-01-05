"use client";

import { withPageAuthRequired } from "@auth0/nextjs-auth0/client";
import {
  Close,
  ExpandMore,
  KeyboardArrowRight,
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
  FormControlLabel,
  FormGroup,
  IconButton,
  InputAdornment,
  Rating,
  TextField,
  Typography,
} from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid-pro";
import {
  DataGridPro as DataGrid,
  GridFooterContainer,
  GridPagination,
} from "@mui/x-data-grid-pro";
import { useCallback, useMemo, useState } from "react";
import * as React from "react";

import type { components } from "@/app/api/apegpt/types.gen";
import HighlightedSQL from "@/app/components/SqlView";
import {
  fetchPromptVersion,
  type GetPromptVersionModel,
  type GetTraceStepModel,
  type QueryExplorerItem,
  type QueryExplorerRequestSummary,
  useQueryExplorer,
  useRequestTrace,
} from "@/app/hooks/useAdminRequests";

type GetDataFetchModel = components["schemas"]["GetDataFetchModel"];

const ROWS_PER_PAGE = 50;

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

// Request type colors
const REQUEST_TYPE_COLORS: Record<
  string,
  "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning"
> = {
  initial: "primary",
  plan_approval: "success",
  plan_amendment: "warning",
  replan: "error",
};

// Map request status to stage label
// FeedbackRequested = Plan (awaiting approval)
// Done/Error = Query (execution completed)
const getStageLabel = (status: string | null | undefined): string => {
  switch (status) {
    case "FeedbackRequested":
      return "Plan";
    case "Done":
    case "Error":
      return "Query";
    default:
      return "Query";
  }
};

// Get chip color based on stage label
const getStageLabelColor = (
  status: string | null | undefined,
):
  | "default"
  | "primary"
  | "secondary"
  | "error"
  | "info"
  | "success"
  | "warning" => {
  switch (status) {
    case "FeedbackRequested":
      return "info";
    case "Done":
      return "success";
    case "Error":
      return "error";
    default:
      return "default";
  }
};

// Status colors
const STATUS_COLORS: Record<
  string,
  "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning"
> = {
  Done: "success",
  Error: "error",
  InProgress: "info",
  New: "default",
  Scheduled: "default",
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

// Custom footer with pagination
const CustomFooter = () => (
  <GridFooterContainer>
    <Box sx={{ flex: 1 }} />
    <GridPagination />
  </GridFooterContainer>
);

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
            {expanded ? <ExpandMore /> : <KeyboardArrowRight />}
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
    } catch {
      // Failed to fetch prompt - dialog will show empty state
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
            {expanded ? <ExpandMore /> : <KeyboardArrowRight />}
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
            {expanded ? <ExpandMore /> : <KeyboardArrowRight />}
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
          {expanded ? <ExpandMore /> : <KeyboardArrowRight />}
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

// Request Detail Drawer - shows full trace for a single request
const RequestDetailDrawer = ({
  request,
  open,
  onClose,
}: {
  request: QueryExplorerRequestSummary | null;
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
        {/* Stage & Status */}
        <Box sx={{ display: "flex", gap: 1 }}>
          <Chip
            label={getStageLabel(request.status)}
            size="small"
            color={getStageLabelColor(request.status)}
            variant="outlined"
          />
          <Chip
            label={request.status}
            size="small"
            color={STATUS_COLORS[request.status] || "default"}
            variant="outlined"
          />
        </Box>

        {/* Request Text */}
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
            {request.request_text}
          </Typography>
        </Box>

        {/* Plan Info */}
        {request.has_plan && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Plan
            </Typography>
            <Box sx={{ mt: 1 }}>
              {request.plan_summary && (
                <Typography variant="body2" sx={{ mb: 1 }}>
                  {request.plan_summary}
                </Typography>
              )}
              {request.plan_tables && request.plan_tables.length > 0 && (
                <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                  {request.plan_tables.map((table) => (
                    <Chip
                      key={table}
                      label={table}
                      size="small"
                      variant="outlined"
                    />
                  ))}
                </Box>
              )}
            </Box>
          </Box>
        )}

        {/* Outcome */}
        {request.outcome && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Outcome
            </Typography>
            <Typography variant="body1">{request.outcome}</Typography>
          </Box>
        )}

        {/* Execution Trace */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Execution Trace
          </Typography>
          <TraceSection requestId={request.request_id} />
        </Box>
      </Box>

      {/* Footer */}
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
          Request: {request.request_id}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Date: {new Date(request.created_at).toLocaleString()}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Duration: {formatDuration(request.trace_duration_ms)}
        </Typography>
      </Box>
    </Drawer>
  );
};

// Request Timeline Item with expandable trace
const RequestTimelineItem = ({
  request,
  index,
  isLast,
  onViewDetails,
}: {
  request: QueryExplorerRequestSummary;
  index: number;
  isLast: boolean;
  onViewDetails: () => void;
}) => {
  const [expanded, setExpanded] = useState(false);
  const stageLabel = getStageLabel(request.status);

  return (
    <Box
      sx={{
        borderBottom: isLast ? "none" : "1px solid",
        borderColor: "divider",
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          p: 1.5,
          cursor: "pointer",
          "&:hover": { backgroundColor: "action.hover" },
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Typography
          variant="caption"
          sx={{
            width: 24,
            height: 24,
            borderRadius: "50%",
            backgroundColor: "primary.main",
            color: "primary.contrastText",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {index + 1}
        </Typography>
        <Chip
          label={stageLabel}
          size="small"
          color={getStageLabelColor(request.status)}
          variant="outlined"
        />
        <Chip
          label={request.status}
          size="small"
          color={STATUS_COLORS[request.status] || "default"}
          variant="outlined"
        />
        <Typography
          variant="body2"
          sx={{
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {request.request_text?.slice(0, 80) || "-"}
          {(request.request_text?.length || 0) > 80 && "..."}
        </Typography>
        {request.trace_llm_calls > 0 && (
          <Chip
            label={`${request.trace_llm_calls} LLM`}
            size="small"
            variant="outlined"
          />
        )}
        <Typography variant="caption" color="text.secondary">
          {formatDuration(request.trace_duration_ms)}
        </Typography>
        <IconButton size="small">
          {expanded ? <ExpandMore /> : <KeyboardArrowRight />}
        </IconButton>
      </Box>

      {/* Expanded content with trace */}
      <Collapse in={expanded}>
        <Box sx={{ px: 2, pb: 2 }}>
          <TraceSection requestId={request.request_id} />
          <Button
            size="small"
            variant="outlined"
            sx={{ mt: 1 }}
            onClick={(e) => {
              e.stopPropagation();
              onViewDetails();
            }}
          >
            View Full Details
          </Button>
        </Box>
      </Collapse>
    </Box>
  );
};

// Query Drawer - shows aggregated trace from all requests
const QueryDrawer = ({
  query,
  open,
  onClose,
  onViewRequest,
}: {
  query: QueryExplorerItem | null;
  open: boolean;
  onClose: () => void;
  onViewRequest: (request: QueryExplorerRequestSummary) => void;
}) => {
  if (!query) return null;

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: "100%", sm: "600px", md: "900px" },
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
        <Typography variant="h6">Query Journey</Typography>
        <IconButton onClick={onClose}>
          <Close />
        </IconButton>
      </Box>

      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          gap: 3,
          flex: 1,
          overflow: "auto",
        }}
      >
        {/* Summary */}
        <Box
          sx={{
            p: 2,
            borderRadius: 1,
            backgroundColor: "action.hover",
          }}
        >
          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
            {query.summary || "Query Summary"}
          </Typography>
          <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
            <Chip
              label={`${query.plan_iterations} plan iteration${query.plan_iterations !== 1 ? "s" : ""}`}
              size="small"
              variant="outlined"
            />
            <Chip
              label={`${query.sql_attempts} SQL attempt${query.sql_attempts !== 1 ? "s" : ""}`}
              size="small"
              variant="outlined"
            />
            {query.had_amendments && (
              <Chip
                label="Had amendments"
                size="small"
                color="warning"
                variant="outlined"
              />
            )}
            {query.had_replan && (
              <Chip
                label="Had replan"
                size="small"
                color="error"
                variant="outlined"
              />
            )}
          </Box>
          <Box sx={{ mt: 2, display: "flex", gap: 3 }}>
            <Typography variant="caption" color="text.secondary">
              Duration: {formatDuration(query.total_duration_ms)}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Tokens: {formatTokens(query.total_tokens_in)} in /{" "}
              {formatTokens(query.total_tokens_out)} out
            </Typography>
          </Box>
        </Box>

        {/* Original Intent */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            Original Intent
          </Typography>
          <Typography
            variant="body1"
            sx={{
              whiteSpace: "pre-wrap",
              backgroundColor: "action.hover",
              p: 2,
              borderRadius: 1,
              mt: 0.5,
            }}
          >
            {query.original_intent || "-"}
          </Typography>
        </Box>

        {/* Final SQL */}
        {query.sql && (
          <Box>
            <Typography
              variant="subtitle2"
              color="text.secondary"
              sx={{ mb: 1 }}
            >
              Final SQL
            </Typography>
            <Box
              sx={{
                maxHeight: "200px",
                overflow: "auto",
                backgroundColor: "background.default",
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 1,
              }}
            >
              <HighlightedSQL code={query.sql} />
            </Box>
            <Button
              variant="outlined"
              size="small"
              sx={{ mt: 1 }}
              onClick={() => window.open(`/q/${query.query_id}`, "_blank")}
            >
              Run Query
            </Button>
          </Box>
        )}

        {/* Request Timeline with full traces */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Request Timeline ({query.requests?.length || 0} requests)
          </Typography>
          <Box
            sx={{
              border: "1px solid",
              borderColor: "divider",
              borderRadius: 1,
            }}
          >
            {query.requests?.map((req, index) => (
              <RequestTimelineItem
                key={req.request_id}
                request={req}
                index={index}
                isLast={index === (query.requests?.length || 0) - 1}
                onViewDetails={() => onViewRequest(req)}
              />
            ))}
            {(!query.requests || query.requests.length === 0) && (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ p: 2, textAlign: "center" }}
              >
                No requests found
              </Typography>
            )}
          </Box>
        </Box>

        {/* Data Fetches */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Data Fetches
          </Typography>
          <DataFetchesSection dataFetches={query.data_fetches} />
        </Box>

        {/* Rating */}
        {query.rating !== null && query.rating !== undefined && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary">
              Rating
            </Typography>
            <Rating value={query.rating} max={10} precision={1} readOnly />
          </Box>
        )}
      </Box>

      {/* Footer */}
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
          User: {query.user || "Unknown"}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Session: {query.session_id}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Query: {query.query_id}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Created: {new Date(query.created_at).toLocaleString()}
        </Typography>
      </Box>
    </Drawer>
  );
};

// Priority order for request types (Plan stages first, then Query)
const REQUEST_TYPE_ORDER: Record<string, number> = {
  initial: 1, // Plan
  plan_amendment: 2, // Plan Amendment
  replan: 3, // Replan
  plan_approval: 4, // Query
};

// Expanded request rows in query accordion
const ExpandedQueryContent = ({
  query,
  onRequestClick,
  selectedRequestId,
}: {
  query: QueryExplorerItem;
  onRequestClick: (request: QueryExplorerRequestSummary) => void;
  selectedRequestId: string | null;
}) => {
  // Sort requests chronologically (same order as Query Journey drawer)
  const sortedRequests = [...(query.requests || [])].sort(
    (a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  return (
    <Box>
      {sortedRequests.map((req) => {
        const stageLabel = getStageLabel(req.status);
        const isQueryStage = stageLabel === "Query";
        const isSelected = req.request_id === selectedRequestId;

        return (
          <Box
            key={req.request_id}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              py: 1,
              px: 2,
              borderBottom: "1px solid",
              borderColor: "divider",
              backgroundColor: isSelected
                ? "rgba(255, 255, 255, 0.08)"
                : "transparent",
              "&:hover": {
                backgroundColor: "rgba(255, 255, 255, 0.04)",
              },
              cursor: "pointer",
            }}
            onClick={() => onRequestClick(req)}
          >
            <Typography
              variant="caption"
              sx={{ width: 170, color: "text.secondary", flexShrink: 0 }}
            >
              {new Date(req.created_at).toLocaleString()}
            </Typography>
            <Chip
              label={stageLabel}
              size="small"
              color={getStageLabelColor(req.status)}
              variant="outlined"
              sx={{ minWidth: 80 }}
            />
            {!isQueryStage && (
              <Typography
                variant="body2"
                sx={{
                  flex: 1,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {req.request_text?.slice(0, 100) || "-"}
              </Typography>
            )}
            {isQueryStage && <Box sx={{ flex: 1 }} />}
            {req.trace_llm_calls > 0 && (
              <Typography variant="caption" color="text.secondary">
                {req.trace_llm_calls} LLM
              </Typography>
            )}
            <Typography variant="caption" color="text.secondary">
              {formatDuration(req.trace_duration_ms)}
            </Typography>
            <Chip
              label={req.status}
              size="small"
              color={STATUS_COLORS[req.status] || "default"}
              variant="outlined"
            />
          </Box>
        );
      })}
      {sortedRequests.length === 0 && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ p: 2, textAlign: "center" }}
        >
          No contributing requests
        </Typography>
      )}
    </Box>
  );
};

const Page = withPageAuthRequired(
  () => {
    const [paginationModel, setPaginationModel] = useState({
      pageSize: ROWS_PER_PAGE,
      page: 0,
    });
    const [searchInput, setSearchInput] = useState("");
    const [search, setSearch] = useState("");
    const [hasFeedback, setHasFeedback] = useState(false);
    const [groupBySession, setGroupBySession] = useState(false);
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
    const [selectedQuery, setSelectedQuery] =
      useState<QueryExplorerItem | null>(null);
    const [queryDrawerOpen, setQueryDrawerOpen] = useState(false);
    const [selectedRequest, setSelectedRequest] =
      useState<QueryExplorerRequestSummary | null>(null);
    const [requestDrawerOpen, setRequestDrawerOpen] = useState(false);

    const { data, total, isLoading } = useQueryExplorer(
      paginationModel.pageSize,
      paginationModel.page * paginationModel.pageSize,
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

    const handleQueryClick = useCallback((query: QueryExplorerItem) => {
      setSelectedQuery(query);
      setQueryDrawerOpen(true);
    }, []);

    const handleRequestClick = useCallback(
      (request: QueryExplorerRequestSummary) => {
        setSelectedRequest(request);
        setRequestDrawerOpen(true);
      },
      [],
    );

    const columns = useMemo<GridColDef<QueryExplorerItem>[]>(
      () => [
        {
          field: "session_id",
          headerName: "Session",
          width: 120,
          sortable: false,
          renderCell: (params) =>
            params.value ? `${String(params.value).slice(0, 8)}...` : "-",
        },
        {
          field: "created_at",
          headerName: "Date",
          width: 190,
          sortable: true,
          renderCell: (params) =>
            new Date(params.value as string).toLocaleString(),
        },
        {
          field: "user",
          headerName: "User",
          width: 200,
          sortable: true,
          renderCell: (params) => params.value || "Unknown",
        },
        {
          field: "original_intent",
          headerName: "Intent",
          flex: 0.3,
          minWidth: 200,
          sortable: false,
          renderCell: (params) => (
            <Box
              sx={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {params.value || "-"}
            </Box>
          ),
        },
        {
          field: "sql",
          headerName: "SQL",
          flex: 0.4,
          minWidth: 250,
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
              {params.value || "-"}
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
      ],
      [],
    );

    const rows = useMemo(
      () =>
        (data || []).map((q: QueryExplorerItem) => ({
          ...q,
          id: q.query_id,
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
        {/* Header with filters */}
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
            Query Explorer
          </Typography>
          <Box sx={{ flex: 1 }} />
          <FormGroup row>
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
            <FormControlLabel
              control={
                <Checkbox
                  checked={groupBySession}
                  onChange={(e) => setGroupBySession(e.target.checked)}
                />
              }
              label="Group by session"
              sx={{ color: "text.primary" }}
            />
          </FormGroup>
          <TextField
            size="small"
            placeholder="Search queries, SQL, or intents..."
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

        {/* DataGrid with detail panels */}
        <Box sx={{ flex: 1, width: "100%", minHeight: 0 }}>
          <DataGrid
            loading={isLoading}
            rows={rows}
            columns={columns}
            density="compact"
            disableRowSelectionOnClick
            pageSizeOptions={[25, 50, 100]}
            slots={{
              footer: CustomFooter,
              detailPanelExpandIcon: KeyboardArrowRight,
              detailPanelCollapseIcon: ExpandMore,
            }}
            paginationModel={paginationModel}
            paginationMode="server"
            onPaginationModelChange={setPaginationModel}
            rowCount={total}
            onRowClick={(params) => {
              // Don't open drawer when clicking on group row
              if (
                params.row.id &&
                !String(params.row.id).startsWith("auto-generated")
              ) {
                handleQueryClick(params.row as QueryExplorerItem);
              }
            }}
            getDetailPanelContent={({ row }) => (
              <ExpandedQueryContent
                query={row as QueryExplorerItem}
                onRequestClick={handleRequestClick}
                selectedRequestId={selectedRequest?.request_id || null}
              />
            )}
            getDetailPanelHeight={() => "auto"}
            detailPanelExpandedRowIds={Array.from(expandedRows)}
            onDetailPanelExpandedRowIdsChange={(ids) => {
              setExpandedRows(new Set(ids.map(String)));
            }}
            columnVisibilityModel={{
              session_id: !groupBySession,
            }}
            treeData={groupBySession}
            getTreeDataPath={(row) =>
              groupBySession ? [row.session_id, row.query_id] : [row.query_id]
            }
            groupingColDef={
              groupBySession
                ? {
                    headerName: "Session",
                    width: 250,
                  }
                : undefined
            }
            defaultGroupingExpansionDepth={groupBySession ? 1 : 0}
            sx={{
              height: "100%",
              border: "none",
              "& .MuiDataGrid-row": {
                cursor: "pointer",
              },
              "& .MuiDataGrid-row:hover": {
                backgroundColor: "action.hover",
              },
              "& .MuiDataGrid-row--detailPanelExpanded": {
                backgroundColor: "rgba(255, 255, 255, 0.03)",
              },
              "& .MuiDataGrid-cell": {
                py: 1,
              },
            }}
          />
        </Box>

        {/* Query Drawer */}
        <QueryDrawer
          query={selectedQuery}
          open={queryDrawerOpen}
          onClose={() => setQueryDrawerOpen(false)}
          onViewRequest={handleRequestClick}
        />

        {/* Request Detail Drawer */}
        <RequestDetailDrawer
          request={selectedRequest}
          open={requestDrawerOpen}
          onClose={() => setRequestDrawerOpen(false)}
        />
      </Box>
    );
  },
  { returnTo: "/admin/queries" },
);

export default Page;
