"use client";

import ThumbDownIcon from "@mui/icons-material/ThumbDown";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import {
  Box,
  CircularProgress,
  Collapse,
  IconButton,
  TextField,
  Tooltip,
} from "@mui/material";
import React, { useCallback, useState } from "react";

import { updateRequest } from "@/app/actions";

interface QueryFeedbackProps {
  requestId: string;
  initialRating?: number | null;
  initialReview?: string | null;
  onRatingChange?: (rating: number) => void;
}

export const QueryFeedback = ({
  requestId,
  initialRating,
  initialReview,
  onRatingChange,
}: QueryFeedbackProps) => {
  const [rating, setRating] = useState<number | null>(initialRating ?? null);
  const [review, setReview] = useState<string>(initialReview ?? "");
  const [showReviewInput, setShowReviewInput] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleThumbUp = useCallback(async () => {
    if (isSubmitting) return;

    const newRating = rating === 10 ? null : 10; // Toggle off if already selected
    setRating(newRating);
    setShowReviewInput(false); // Hide review input on thumb up

    try {
      setIsSubmitting(true);
      await updateRequest({
        requestId,
        data: { rating: newRating ?? 0, review: "" },
      });
      onRatingChange?.(newRating ?? 0);
    } catch (error) {
      console.error("Failed to update rating:", error);
      setRating(rating); // Revert on error
    } finally {
      setIsSubmitting(false);
    }
  }, [requestId, rating, isSubmitting, onRatingChange]);

  const handleThumbDown = useCallback(async () => {
    if (isSubmitting) return;

    if (rating === 1) {
      // Toggle off if already selected
      setRating(null);
      setShowReviewInput(false);
      try {
        setIsSubmitting(true);
        await updateRequest({
          requestId,
          data: { rating: 0, review: "" },
        });
        onRatingChange?.(0);
      } catch (error) {
        console.error("Failed to update rating:", error);
        setRating(rating);
      } finally {
        setIsSubmitting(false);
      }
    } else {
      // Select thumb down and show review input
      setRating(1);
      setShowReviewInput(true);
      try {
        setIsSubmitting(true);
        await updateRequest({
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
    }
  }, [requestId, rating, isSubmitting, onRatingChange]);

  const handleReviewSubmit = useCallback(async () => {
    if (isSubmitting || !review.trim()) return;

    try {
      setIsSubmitting(true);
      await updateRequest({
        requestId,
        data: { rating: rating ?? 1, review: review.trim() },
      });
      setShowReviewInput(false);
    } catch (error) {
      console.error("Failed to submit review:", error);
    } finally {
      setIsSubmitting(false);
    }
  }, [requestId, rating, review, isSubmitting]);

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
    <Box>
      <Box sx={{ display: "flex", alignItems: "center" }}>
        <Tooltip title="Good response">
          <IconButton
            size="small"
            onClick={handleThumbUp}
            disabled={isSubmitting}
            sx={{ opacity: isSubmitting ? 0.5 : 1 }}
          >
            {isSubmitting && rating === 10 ? (
              <CircularProgress size={16} />
            ) : (
              <ThumbUpIcon
                fontSize="small"
                color={rating === 10 ? "success" : "disabled"}
              />
            )}
          </IconButton>
        </Tooltip>
        <Tooltip title="Poor response">
          <IconButton
            size="small"
            onClick={handleThumbDown}
            disabled={isSubmitting}
            sx={{ opacity: isSubmitting ? 0.5 : 1 }}
          >
            {isSubmitting && rating === 1 ? (
              <CircularProgress size={16} />
            ) : (
              <ThumbDownIcon
                fontSize="small"
                color={rating === 1 ? "error" : "disabled"}
              />
            )}
          </IconButton>
        </Tooltip>
      </Box>
      <Collapse in={showReviewInput}>
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
          onBlur={handleReviewSubmit}
          sx={{ mt: 1 }}
          InputProps={{
            sx: { fontSize: "0.875rem" },
          }}
        />
      </Collapse>
    </Box>
  );
};
