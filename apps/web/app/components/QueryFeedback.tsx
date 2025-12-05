"use client";

import CheckIcon from "@mui/icons-material/Check";
import SendIcon from "@mui/icons-material/Send";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import { Box, Collapse, IconButton, TextField, Tooltip } from "@mui/material";
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

  const handleThumbUp = useCallback(async () => {
    if (isSubmitting) return;

    const newRating = rating === 10 ? null : 10;
    setRating(newRating);
    setShowReviewInput(false);

    try {
      setIsSubmitting(true);
      await updateRequest({
        sessionId,
        requestId,
        data: { rating: newRating ?? 0, review: "" },
      });
      onRatingChange?.(newRating ?? 0);
    } catch (error) {
      console.error("Failed to update rating:", error);
      setRating(rating);
    } finally {
      setIsSubmitting(false);
    }
  }, [sessionId, requestId, rating, isSubmitting, onRatingChange]);

  const handleThumbDown = useCallback(async () => {
    if (isSubmitting || showCheck) return;

    if (rating === 1 && !showReviewInput) {
      setShowReviewInput(true);
      return;
    }

    if (rating === 1 && showReviewInput) {
      setShowReviewInput(false);
      return;
    }

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
  }, [
    sessionId,
    requestId,
    rating,
    isSubmitting,
    showReviewInput,
    showCheck,
    onRatingChange,
  ]);

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
        <Box sx={{ display: "flex", alignItems: "center" }}>
          <Tooltip title="Good response">
            <IconButton
              size="small"
              onClick={handleThumbUp}
              disabled={isSubmitting}
            >
              <Box
                component={ThumbUpIcon}
                sx={{
                  width: 16,
                  height: 16,
                  color: rating === 10 ? "text.primary" : "text.secondary",
                }}
              />
            </IconButton>
          </Tooltip>
          <Tooltip title="Poor response">
            <IconButton
              size="small"
              onClick={handleThumbDown}
              disabled={isSubmitting}
            >
              <Box
                component={showCheck ? CheckIcon : ThumbDownIcon}
                sx={{
                  width: 16,
                  height: 16,
                  color:
                    rating === 1 || showCheck
                      ? "text.primary"
                      : "text.secondary",
                }}
              />
            </IconButton>
          </Tooltip>
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
    </Box>
  );
};
