"use client";

import CheckIcon from "@mui/icons-material/Check";
import SendIcon from "@mui/icons-material/Send";
import {
  Box,
  Button,
  Collapse,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import React, { useCallback, useState } from "react";

import { updateRequest } from "@/app/actions";

interface QueryFeedbackProps {
  requestId: string;
  sessionId: string;
  initialRating?: number | null;
  initialReview?: string | null;
  onRatingChange?: (rating: number) => void;
  children?: React.ReactNode; // Other action buttons to render inline
}

export const QueryFeedback = ({
  requestId,
  sessionId,
  initialRating,
  initialReview,
  onRatingChange,
  children,
}: QueryFeedbackProps) => {
  const [rating, setRating] = useState<number | null>(initialRating ?? null);
  const [review, setReview] = useState<string>(initialReview ?? "");
  const [showReviewInput, setShowReviewInput] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showCheck, setShowCheck] = useState(false);

  const hasFeedback = rating !== null;

  const handleYes = useCallback(async () => {
    if (isSubmitting) return;

    setRating(10);
    setShowReviewInput(false);

    try {
      setIsSubmitting(true);
      await updateRequest({
        sessionId,
        requestId,
        data: { rating: 10, review: "" },
      });
      onRatingChange?.(10);
    } catch (error) {
      console.error("Failed to update rating:", error);
      setRating(rating);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, requestId, rating, isSubmitting, onRatingChange]);

  const handleNo = useCallback(async () => {
    if (isSubmitting || showCheck) return;

    setRating(1);
    setShowReviewInput(true);

    try {
      setIsSubmitting(true);
      await updateRequest({
        sessionId,
        requestId,
        data: { rating: 1, review: "" },
      });
      onRatingChange?.(1);
    } catch (error) {
      console.error("Failed to update rating:", error);
      setRating(rating);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, requestId, rating, isSubmitting, showCheck, onRatingChange]);

  const handleReviewSubmit = useCallback(async () => {
    if (isSubmitting) return;

    try {
      setIsSubmitting(true);
      await updateRequest({
        sessionId,
        requestId,
        data: { rating: rating ?? 1, review: review.trim() },
      });

      setShowReviewInput(false);
      setShowCheck(true);

      setTimeout(() => {
        setShowCheck(false);
      }, 2000);
    } catch (error) {
      console.error("Failed to submit review:", error);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, requestId, rating, review, isSubmitting]);

  const handleReviewKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleReviewSubmit();
      }
      if (e.key === "Escape") {
        setShowReviewInput(false);
      }
    },
    [handleReviewSubmit],
  );

  return (
    <Box sx={{ width: "100%" }}>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          {!hasFeedback && (
            <>
              <Typography
                variant="body2"
                sx={{ color: "text.secondary", fontSize: "0.8rem" }}
              >
                Help us improve: Was this answer accurate?
              </Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={handleYes}
                disabled={isSubmitting}
                sx={{
                  minWidth: "auto",
                  px: 1,
                  py: 0.25,
                  fontSize: "0.75rem",
                  textTransform: "none",
                }}
              >
                Yes
              </Button>
              <Button
                size="small"
                variant="outlined"
                onClick={handleNo}
                disabled={isSubmitting}
                sx={{
                  minWidth: "auto",
                  px: 1,
                  py: 0.25,
                  fontSize: "0.75rem",
                  textTransform: "none",
                }}
              >
                No
              </Button>
            </>
          )}
          {hasFeedback && showCheck && (
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <CheckIcon
                sx={{ width: 16, height: 16, color: "text.primary" }}
              />
              <Typography
                variant="body2"
                sx={{ color: "text.secondary", fontSize: "0.8rem" }}
              >
                Thanks for your feedback
              </Typography>
            </Box>
          )}
        </Box>
        {children}
      </Box>
      <Collapse in={showReviewInput}>
        <Box sx={{ display: "flex", alignItems: "flex-end", gap: 1, mt: 1 }}>
          <TextField
            size="small"
            multiline
            minRows={2}
            maxRows={4}
            fullWidth
            placeholder="What went wrong? (optional)"
            value={review}
            onChange={(e) => setReview(e.target.value)}
            onKeyDown={handleReviewKeyDown}
            InputProps={{
              sx: { fontSize: "0.875rem" },
            }}
          />
          <Tooltip title="Submit feedback">
            <IconButton
              size="small"
              onClick={handleReviewSubmit}
              disabled={isSubmitting}
              sx={{ mb: 0.5 }}
            >
              <Box
                component={SendIcon}
                sx={{
                  width: 16,
                  height: 16,
                  color: "text.secondary",
                }}
              />
            </IconButton>
          </Tooltip>
        </Box>
      </Collapse>
      {/* Display saved review when not editing */}
      {!showReviewInput && review && (
        <Typography
          variant="body2"
          sx={{
            mt: 1,
            color: "text.secondary",
            fontStyle: "italic",
            fontSize: "0.8rem",
          }}
        >
          Feedback: {review}
        </Typography>
      )}
    </Box>
  );
};
