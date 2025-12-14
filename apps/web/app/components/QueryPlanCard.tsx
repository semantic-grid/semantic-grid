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
import { useState } from "react";

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

  // Use controlled state for accordions - start collapsed if user already made selection
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const [assumptionsExpanded, setAssumptionsExpanded] = useState(
    userSelection === null,
  );
  const [paramsExpanded, setParamsExpanded] = useState(false);

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
        expanded={detailsExpanded}
        onChange={(_, expanded) => setDetailsExpanded(expanded)}
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
          expanded={assumptionsExpanded}
          onChange={(_, expanded) => setAssumptionsExpanded(expanded)}
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
          expanded={paramsExpanded}
          onChange={(_, expanded) => setParamsExpanded(expanded)}
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

      {/* Action Buttons - show only selected button when user has acted */}
      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {/* Show Reject button: when no selection, or when rejected */}
        {(userSelection === null || userSelection === "rejected") && (
          <Button
            variant="text"
            color="error"
            size="small"
            startIcon={<CloseIcon sx={{ fontSize: "1rem" }} />}
            onClick={onReject}
            disabled={isLoading || userSelection === "rejected"}
            sx={{ textTransform: "none" }}
          >
            Reject
          </Button>
        )}
        {/* Show Approve button: when no selection, or when approved */}
        {(userSelection === null || userSelection === "approved") && (
          <Button
            variant="text"
            color="success"
            size="small"
            startIcon={<CheckIcon sx={{ fontSize: "1rem" }} />}
            onClick={onApprove}
            disabled={isLoading || userSelection === "approved"}
            sx={{ textTransform: "none" }}
          >
            Approve & Generate SQL
          </Button>
        )}
        {/* Show feedback indicator when user commented */}
        {userSelection === "commented" && (
          <Typography variant="caption" color="text.secondary">
            Feedback provided
          </Typography>
        )}
      </Stack>
    </Box>
  );
};
