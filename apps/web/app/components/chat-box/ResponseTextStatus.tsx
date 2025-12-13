import { ArrowRight } from "@mui/icons-material";
import type { StepIconProps } from "@mui/material";
import { Stack, Step, StepLabel, Typography } from "@mui/material";
import { keyframes, styled } from "@mui/material/styles";
import React from "react";

// Define the keyframes for pulsing opacity
const pulse = keyframes`
  0% { opacity: 1; }
  50% { opacity: 0.1; }
  100% { opacity: 1; }
`;

// Styled Typography with pulsing animation
const PulsingText = styled(Typography)(({ theme }) => ({
  color: theme.palette.grey[500],
  animation: `${pulse} 1.5s ease-in-out infinite`,
}));

const Status: Record<string, string> = {
  New: "Starting...",
  Intent: "Analyzing intent...",
  Planning: "Planning query...",
  FeedbackRequested: "Awaiting approval...",
  PlanRejected: "Plan rejected. What would you like to do instead?",
  SQL: "Generating query...",
  Retry: "Refining response...",
  DataFetch: "Fetching data...",
  Finalizing: "Finalizing...",
  Cancelled: "Cancelled",
  Error: "Error",
};

const RequestStages = ["Intent", "Planning", "SQL", "Finalizing"];

const CustomStepIcon = (props: StepIconProps) => (
  <ArrowRight sx={{ fontSize: "small", ml: "5px" }} />
);

export const ResponseTextStatus = ({
  status,
  rowCount,
  linkedSession,
  isLoading = false,
  lastMessage = false,
  requestText,
  isLinkedQuery = false,
}: {
  status?: string;
  rowCount?: number;
  isLoading?: boolean;
  lastMessage?: boolean;
  linkedSession?: string; // whether to show the link icon
  requestText?: string; // the user's request text
  isLinkedQuery?: boolean; // whether this is a linked query being summarized
}) => {
  // For /new and /help requests, show simple "Working..." instead of stages
  const isDiscoveryRequest = requestText === "/new" || requestText === "/help";

  // For linked queries being summarized, show "Summarizing..." instead of stages
  const isLinkedQuerySummarizing =
    isLinkedQuery &&
    status &&
    status !== "Done" &&
    status !== "Error" &&
    status !== "Cancelled";

  if (
    lastMessage &&
    isDiscoveryRequest &&
    status &&
    status !== "Done" &&
    status !== "Error" &&
    status !== "Cancelled"
  ) {
    return <PulsingText variant="body2">Working...</PulsingText>;
  }

  if (lastMessage && isLinkedQuerySummarizing) {
    return <PulsingText variant="body2">Summarizing...</PulsingText>;
  }

  // FeedbackRequested is a terminal-like state waiting for user action
  if (lastMessage && status === "FeedbackRequested") {
    return (
      <Typography variant="body2" color="primary">
        {Status[status]}
      </Typography>
    );
  }

  // PlanRejected - user rejected the plan and can start fresh
  if (lastMessage && status === "PlanRejected") {
    return (
      <Typography variant="body2" color="warning.main">
        {Status[status]}
      </Typography>
    );
  }

  if (
    lastMessage &&
    (status === "Cancelled" || status === "Error" || status === "Done")
  ) {
    /*
    if (status === "Done" && (rowCount || 0) === 0 && !isLoading) {
      return (
        <Typography variant="body2" color="textSecondary">
          (No data returned)
        </Typography>
      );
    }
     */
    return Status[status] ? (
      <Typography variant="body1">{Status[status]}</Typography>
    ) : null;
  }

  if (lastMessage && status && RequestStages.includes(status)) {
    const currentStage = RequestStages.indexOf(status);
    return (
      <Stack direction="row" alignItems="center">
        {RequestStages.map((s, idx) => (
          <Step key={s} completed={s === status}>
            <StepLabel
              sx={{
                "& .MuiStepLabel-iconContainer": {
                  display: idx === 0 ? "none" : "flex", // hide icon container if no icon
                },
                "& span": { ml: 0, pl: 0 },
              }}
              StepIconComponent={idx === 0 ? () => null : CustomStepIcon}
            >
              {s !== status && idx < currentStage && (
                <Typography variant="body2">{s}</Typography>
              )}
              {s !== status && idx > currentStage && (
                <Typography variant="body2" color="darkgrey">
                  {s}
                </Typography>
              )}
              {s === status && <PulsingText variant="body2">{s}</PulsingText>}
            </StepLabel>
          </Step>
        ))}
      </Stack>
    );
    // return <PulsingText variant="body2">{Status[status]}</PulsingText>;
  }
  if (status === "Error") {
    return (
      <Typography variant="body1" color="warning">
        Error
      </Typography>
    );
  }
  if (status) return null;
  return null;
};
