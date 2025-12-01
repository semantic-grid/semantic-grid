/**
 * Global SWR configuration with smart retry strategies
 *
 * Handles:
 * - Exponential backoff for retries
 * - Respect for Retry-After headers (503 responses)
 * - Circuit breaker integration
 * - No retry on client errors (4xx)
 */

import type { SWRConfiguration } from "swr";

import { executeWithCircuitBreaker } from "./circuitBreaker";

/**
 * Extract Retry-After header from response
 */
function getRetryAfter(error: any): number | null {
  if (!error?.response?.headers) return null;

  const retryAfter =
    error.response.headers.get?.("Retry-After") ||
    error.response.headers["retry-after"];

  if (!retryAfter) return null;

  const seconds = parseInt(retryAfter, 10);
  return Number.isNaN(seconds) ? null : seconds;
}

/**
 * Check if error is a server error that should trigger retry
 */
function isRetriableError(error: any): boolean {
  if (!error?.status && !error?.response?.status) {
    // Network errors are retriable
    return true;
  }

  const status = error.status || error.response?.status;

  // Don't retry on client errors (4xx)
  if (status >= 400 && status < 500) {
    return false;
  }

  // Retry on server errors (5xx) and network errors
  return true;
}

/**
 * Default SWR configuration with smart retry
 */
export const defaultSWRConfig: SWRConfiguration = {
  // Retry strategy with exponential backoff
  onErrorRetry: (error, key, config, revalidate, { retryCount }) => {
    // Check if error should be retried
    if (!isRetriableError(error)) {
      // eslint-disable-next-line no-console
      console.log(`[SWR] Not retrying ${key} - client error ${error.status}`);
      return;
    }

    // Max 3 retries
    if (retryCount >= 3) {
      // eslint-disable-next-line no-console
      console.log(`[SWR] Max retries reached for ${key}`);
      return;
    }

    // Check for Retry-After header (from 503 responses)
    const retryAfter = getRetryAfter(error);
    if (retryAfter !== null) {
      // eslint-disable-next-line no-console
      console.log(`[SWR] Respecting Retry-After: ${retryAfter}s for ${key}`);
      setTimeout(() => revalidate({ retryCount }), retryAfter * 1000);
      return;
    }

    // Exponential backoff: 1s, 2s, 4s
    const backoffMs = 2 ** retryCount * 1000;
    // eslint-disable-next-line no-console
    console.log(
      `[SWR] Retrying ${key} in ${backoffMs}ms (attempt ${retryCount + 1}/3)`,
    );
    setTimeout(() => revalidate({ retryCount }), backoffMs);
  },

  // Don't revalidate on focus during errors to prevent retry storms
  revalidateOnFocus: false,

  // Don't revalidate on reconnect during errors
  revalidateOnReconnect: false,

  // Deduplicate requests in 2 second window
  dedupingInterval: 2000,

  // Keep previous data while revalidating
  keepPreviousData: true,

  // Error retry interval (fallback if onErrorRetry not used)
  errorRetryInterval: 5000,

  // Maximum number of retries
  errorRetryCount: 3,

  // Don't show error from first failed request immediately
  shouldRetryOnError: true,
};

/**
 * Create a fetcher with circuit breaker protection
 */
export function createFetcherWithCircuitBreaker(
  baseFetcher: (url: string, init?: RequestInit) => Promise<any>,
) {
  return async (url: string, init?: RequestInit) =>
    executeWithCircuitBreaker(() => baseFetcher(url, init), url);
}

/**
 * Parse error details for user-friendly messages
 */
export function parseErrorMessage(error: any): string {
  // Circuit breaker error
  if (error?.message?.includes("Circuit breaker is OPEN")) {
    return error.message;
  }

  // 503 Service Unavailable
  if (error?.status === 503 || error?.response?.status === 503) {
    const body = error?.response?.data || error?.data;
    if (body?.message) {
      return body.message;
    }
    return "Server is temporarily busy. Please wait a moment and try again.";
  }

  // 500 Server Error
  if (error?.status >= 500 || error?.response?.status >= 500) {
    return "Server error occurred. Please try again in a moment.";
  }

  // Network error
  if (
    error?.message === "Failed to fetch" ||
    error?.message?.includes("NetworkError")
  ) {
    return "Network connection issue. Please check your internet connection.";
  }

  // Default
  return error?.message || "An unexpected error occurred";
}
