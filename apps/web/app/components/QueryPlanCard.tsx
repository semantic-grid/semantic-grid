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
  Stack,
  Typography,
} from "@mui/material";

import type { TQueryPlan } from "@/app/lib/types";

type UserSelection = "approved" | "rejected" | "commented" | null;

interface QueryPlanCardProps {
  plan: TQueryPlan;
  onApprove: () => void;
  onReject: () => void;
  isLoading?: boolean;
  userSelection?: UserSelection;
}

export const QueryPlanCard = ({
  plan,
  onApprove,
  onReject,
  isLoading = false,
  userSelection = null,
}: QueryPlanCardProps) => {
  const getComplexityColor = () => {
    if (plan.estimated_complexity === "simple") return "success";
    if (plan.estimated_complexity === "moderate") return "warning";
    return "error";
  };
  const complexityColor = getComplexityColor();

  return (
    <Box
      sx={{
        py: 1,
        my: 1,
      }}
    >
      {/* Header */}
      <Box sx={{ mb: 1 }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
        >
          <Typography variant="body2" fontWeight={500}>
            Query Plan
          </Typography>
          <Chip
            label={plan.estimated_complexity}
            color={complexityColor}
            size="small"
            sx={{ height: 20, fontSize: "0.7rem" }}
          />
        </Stack>
      </Box>

      {/* Plan Summary */}
      <Box sx={{ mb: 1 }}>
        <Typography variant="body2" sx={{ fontStyle: "italic" }}>
          {plan.plan_summary}
        </Typography>
      </Box>

      <Divider sx={{ my: 1 }} />

      {/* Details Accordion */}
      <Accordion
        defaultExpanded={false}
        disableGutters
        elevation={0}
        sx={{
          "&:before": { display: "none" },
          backgroundColor: "transparent",
        }}
      >
        <AccordionSummary
          expandIcon={<ExpandMoreIcon sx={{ fontSize: "1rem" }} />}
          sx={{
            minHeight: 32,
            px: 0,
            "& .MuiAccordionSummary-content": { my: 0.5 },
          }}
        >
          <Typography variant="body2">Details</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, py: 0.5 }}>
          {/* Tables */}
          <Box sx={{ mb: 1 }}>
            <Typography variant="caption" color="text.secondary">
              Tables
            </Typography>
            <Stack
              direction="row"
              spacing={0.5}
              flexWrap="wrap"
              sx={{ mt: 0.5 }}
            >
              {plan.tables.map((table) => (
                <Chip
                  key={table}
                  label={table}
                  size="small"
                  variant={table === plan.primary_table ? "filled" : "outlined"}
                  color={table === plan.primary_table ? "primary" : "default"}
                  sx={{ height: 20, fontSize: "0.7rem" }}
                />
              ))}
            </Stack>
          </Box>

          {/* Columns */}
          {plan.columns_selected.length > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Columns Selected
              </Typography>
              <List dense disablePadding>
                {plan.columns_selected.map((col) => (
                  <ListItem key={col} sx={{ py: 0, px: 0 }}>
                    <ListItemText
                      primary={col}
                      primaryTypographyProps={{ variant: "body2" }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Filters */}
          {plan.filters.length > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Filters
              </Typography>
              <List dense disablePadding>
                {plan.filters.map((filter) => (
                  <ListItem
                    key={
                      typeof filter === "string"
                        ? filter
                        : `${filter.column}-${filter.operator}-${filter.value}`
                    }
                    sx={{ py: 0, px: 0 }}
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
                      primaryTypographyProps={{ variant: "body2" }}
                      secondaryTypographyProps={{ variant: "caption" }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Aggregations */}
          {plan.aggregations.length > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Aggregations
              </Typography>
              <List dense disablePadding>
                {plan.aggregations.map((agg) => (
                  <ListItem
                    key={
                      typeof agg === "string"
                        ? agg
                        : `${agg.function}-${agg.column || "*"}-${agg.alias || ""}`
                    }
                    sx={{ py: 0, px: 0 }}
                  >
                    <ListItemText
                      primary={
                        typeof agg === "string"
                          ? agg
                          : `${agg.function}(${agg.column || "*"})${agg.alias ? ` as ${agg.alias}` : ""}`
                      }
                      primaryTypographyProps={{ variant: "body2" }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Joins */}
          {plan.joins.length > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Joins
              </Typography>
              <List dense disablePadding>
                {plan.joins.map((join) => (
                  <ListItem
                    key={
                      typeof join === "string"
                        ? join
                        : `${join.left_table}-${join.right_table}-${join.join_type}`
                    }
                    sx={{ py: 0, px: 0 }}
                  >
                    <ListItemText
                      primary={
                        typeof join === "string"
                          ? join
                          : `${join.join_type.toUpperCase()} JOIN ${join.right_table} ${join.join_condition}`
                      }
                      primaryTypographyProps={{ variant: "body2" }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Group By */}
          {plan.group_by.length > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Group By
              </Typography>
              <Typography variant="body2">
                {plan.group_by.join(", ")}
              </Typography>
            </Box>
          )}

          {/* Order By */}
          {plan.order_by.length > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Order By
              </Typography>
              <Typography variant="body2">
                {plan.order_by.join(", ")}
              </Typography>
            </Box>
          )}

          {/* Limit */}
          {plan.limit && (
            <Box sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Limit
              </Typography>
              <Typography variant="body2">{plan.limit} rows</Typography>
            </Box>
          )}
        </AccordionDetails>
      </Accordion>

      {/* Assumptions */}
      {plan.assumptions.length > 0 && (
        <Accordion
          defaultExpanded
          disableGutters
          elevation={0}
          sx={{
            "&:before": { display: "none" },
            backgroundColor: "transparent",
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon sx={{ fontSize: "1rem" }} />}
            sx={{
              minHeight: 32,
              px: 0,
              "& .MuiAccordionSummary-content": { my: 0.5 },
            }}
          >
            <Typography variant="body2">
              Assumptions ({plan.assumptions.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, py: 0.5 }}>
            <List dense disablePadding>
              {plan.assumptions.map((assumption) => (
                <ListItem key={assumption} sx={{ py: 0.25, px: 0 }}>
                  <ListItemText
                    primary={assumption}
                    primaryTypographyProps={{ variant: "body2" }}
                  />
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Default Parameters */}
      {plan.default_params.length > 0 && (
        <Accordion
          disableGutters
          elevation={0}
          sx={{
            "&:before": { display: "none" },
            backgroundColor: "transparent",
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon sx={{ fontSize: "1rem" }} />}
            sx={{
              minHeight: 32,
              px: 0,
              "& .MuiAccordionSummary-content": { my: 0.5 },
            }}
          >
            <Typography variant="body2">
              Default Parameters ({plan.default_params.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, py: 0.5 }}>
            <List dense disablePadding>
              {plan.default_params.map((param) => (
                <ListItem key={param} sx={{ py: 0.25, px: 0 }}>
                  <ListItemText
                    primary={param}
                    primaryTypographyProps={{ variant: "body2" }}
                  />
                </ListItem>
              ))}
            </List>
          </AccordionDetails>
        </Accordion>
      )}

      <Divider sx={{ my: 1 }} />

      {/* Action Buttons or User Selection State */}
      {userSelection ? (
        <Box sx={{ textAlign: "right" }}>
          <Typography variant="caption" color="text.secondary">
            {userSelection === "approved" && "Approved"}
            {userSelection === "rejected" && "Rejected"}
            {userSelection === "commented" && "Feedback provided"}
          </Typography>
        </Box>
      ) : (
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button
            variant="text"
            color="error"
            size="small"
            startIcon={<CloseIcon sx={{ fontSize: "1rem" }} />}
            onClick={onReject}
            disabled={isLoading}
            sx={{ textTransform: "none" }}
          >
            Reject
          </Button>
          <Button
            variant="text"
            color="success"
            size="small"
            startIcon={<CheckIcon sx={{ fontSize: "1rem" }} />}
            onClick={onApprove}
            disabled={isLoading}
            sx={{ textTransform: "none" }}
          >
            Approve & Generate SQL
          </Button>
        </Stack>
      )}
    </Box>
  );
};
