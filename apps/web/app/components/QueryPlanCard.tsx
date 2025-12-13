"use client";

import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  Typography,
} from "@mui/material";

import type { TQueryPlan } from "@/app/lib/types";

interface QueryPlanCardProps {
  plan: TQueryPlan;
  onApprove: () => void;
  onReject: () => void;
  isLoading?: boolean;
}

export const QueryPlanCard = ({
  plan,
  onApprove,
  onReject,
  isLoading = false,
}: QueryPlanCardProps) => {
  const getComplexityColor = () => {
    if (plan.estimated_complexity === "simple") return "success";
    if (plan.estimated_complexity === "moderate") return "warning";
    return "error";
  };
  const complexityColor = getComplexityColor();

  return (
    <Paper
      elevation={2}
      sx={{
        p: 2,
        my: 2,
        backgroundColor: "background.paper",
        border: "1px solid",
        borderColor: "divider",
      }}
    >
      {/* Header */}
      <Box sx={{ mb: 2 }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
        >
          <Typography variant="h6" component="h3">
            Query Plan
          </Typography>
          <Chip
            label={plan.estimated_complexity}
            color={complexityColor}
            size="small"
          />
        </Stack>
      </Box>

      {/* Plan Summary */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="body1" sx={{ fontStyle: "italic" }}>
          {plan.plan_summary}
        </Typography>
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* Details Accordion */}
      <Accordion defaultExpanded={false}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">Details</Typography>
        </AccordionSummary>
        <AccordionDetails>
          {/* Tables */}
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" color="text.secondary">
              Tables
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 0.5 }}>
              {plan.tables.map((table) => (
                <Chip
                  key={table}
                  label={table}
                  size="small"
                  variant={table === plan.primary_table ? "filled" : "outlined"}
                  color={table === plan.primary_table ? "primary" : "default"}
                />
              ))}
            </Stack>
          </Box>

          {/* Columns */}
          {plan.columns_selected.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Columns Selected
              </Typography>
              <List dense>
                {plan.columns_selected.map((col) => (
                  <ListItem key={col} sx={{ py: 0 }}>
                    <ListItemText primary={col} />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Filters */}
          {plan.filters.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Filters
              </Typography>
              <List dense>
                {plan.filters.map((filter) => (
                  <ListItem
                    key={
                      typeof filter === "string"
                        ? filter
                        : `${filter.column}-${filter.operator}-${filter.value}`
                    }
                    sx={{ py: 0 }}
                  >
                    <ListItemText
                      primary={
                        typeof filter === "string"
                          ? filter
                          : `${filter.column} ${filter.operator} ${filter.value}`
                      }
                      secondary={
                        typeof filter !== "string" ? filter.source : undefined
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Aggregations */}
          {plan.aggregations.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Aggregations
              </Typography>
              <List dense>
                {plan.aggregations.map((agg) => (
                  <ListItem
                    key={
                      typeof agg === "string"
                        ? agg
                        : `${agg.function}-${agg.column || "*"}-${agg.alias || ""}`
                    }
                    sx={{ py: 0 }}
                  >
                    <ListItemText
                      primary={
                        typeof agg === "string"
                          ? agg
                          : `${agg.function}(${agg.column || "*"})${agg.alias ? ` as ${agg.alias}` : ""}`
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Joins */}
          {plan.joins.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Joins
              </Typography>
              <List dense>
                {plan.joins.map((join) => (
                  <ListItem
                    key={
                      typeof join === "string"
                        ? join
                        : `${join.left_table}-${join.right_table}-${join.join_type}`
                    }
                    sx={{ py: 0 }}
                  >
                    <ListItemText
                      primary={
                        typeof join === "string"
                          ? join
                          : `${join.join_type.toUpperCase()} JOIN ${join.right_table} ${join.join_condition}`
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Group By */}
          {plan.group_by.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Group By
              </Typography>
              <Typography variant="body2">
                {plan.group_by.join(", ")}
              </Typography>
            </Box>
          )}

          {/* Order By */}
          {plan.order_by.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Order By
              </Typography>
              <Typography variant="body2">
                {plan.order_by.join(", ")}
              </Typography>
            </Box>
          )}

          {/* Limit */}
          {plan.limit && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Limit
              </Typography>
              <Typography variant="body2">{plan.limit} rows</Typography>
            </Box>
          )}
        </AccordionDetails>
      </Accordion>

      {/* Assumptions */}
      {plan.assumptions.length > 0 && (
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2">
              Assumptions ({plan.assumptions.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <List dense>
              {plan.assumptions.map((assumption) => (
                <ListItem key={assumption} sx={{ py: 0 }}>
                  <ListItemText primary={assumption} />
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Default Parameters */}
      {plan.default_params.length > 0 && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2">
              Default Parameters ({plan.default_params.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <List dense>
              {plan.default_params.map((param) => (
                <ListItem key={param} sx={{ py: 0 }}>
                  <ListItemText primary={param} />
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      <Divider sx={{ my: 2 }} />

      {/* Action Buttons */}
      <Stack direction="row" spacing={2} justifyContent="flex-end">
        <Button
          variant="outlined"
          color="error"
          startIcon={<CloseIcon />}
          onClick={onReject}
          disabled={isLoading}
        >
          Reject
        </Button>
        <Button
          variant="contained"
          color="success"
          startIcon={<CheckIcon />}
          onClick={onApprove}
          disabled={isLoading}
        >
          Approve & Generate SQL
        </Button>
      </Stack>
    </Paper>
  );
};
