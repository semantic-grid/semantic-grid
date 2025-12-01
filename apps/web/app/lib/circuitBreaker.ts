/**
 * Circuit Breaker Pattern for API calls
 *
 * Prevents cascading failures by detecting when a service is down
 * and failing fast instead of overwhelming it with retries.
 *
 * States:
 * - CLOSED: Normal operation, requests go through
 * - OPEN: Service is down, requests fail immediately
 * - HALF_OPEN: Testing if service recovered, limited requests allowed
 */

type CircuitState = "CLOSED" | "OPEN" | "HALF_OPEN";

interface CircuitBreakerState {
  failures: number;
  lastFailureTime: number;
  state: CircuitState;
  consecutiveSuccesses: number;
}

// Configuration
const FAILURE_THRESHOLD = 5; // Open circuit after 5 consecutive failures
const TIMEOUT_MS = 30000; // Wait 30s before trying again (OPEN -> HALF_OPEN)
const SUCCESS_THRESHOLD = 2; // Close circuit after 2 consecutive successes in HALF_OPEN

// Global state
const circuitState: CircuitBreakerState = {
  failures: 0,
  lastFailureTime: 0,
  state: "CLOSED",
  consecutiveSuccesses: 0,
};

/**
 * Handle successful request
 */
function onSuccess(identifier?: string) {
  if (circuitState.state === "HALF_OPEN") {
    circuitState.consecutiveSuccesses++;

    if (circuitState.consecutiveSuccesses >= SUCCESS_THRESHOLD) {
      // eslint-disable-next-line no-console
      console.log(
        `[Circuit Breaker ${identifier || ""}] HALF_OPEN -> CLOSED (service recovered)`,
      );
      circuitState.state = "CLOSED";
      circuitState.failures = 0;
      circuitState.consecutiveSuccesses = 0;
    }
  } else if (circuitState.state === "CLOSED") {
    // Reset failure count on success
    circuitState.failures = 0;
  }
}

/**
 * Handle failed request
 */
function onFailure(error: unknown, identifier?: string) {
  circuitState.failures++;
  circuitState.lastFailureTime = Date.now();

  // Only count 503 and 5xx errors as circuit-breaking failures
  const isServerError =
    error &&
    typeof error === "object" &&
    "status" in error &&
    typeof error.status === "number" &&
    error.status >= 500;

  if (!isServerError) {
    // Don't count client errors (4xx) toward circuit breaking
    return;
  }

  if (circuitState.state === "HALF_OPEN") {
    // Failed during half-open test, go back to open
    // eslint-disable-next-line no-console
    console.log(
      `[Circuit Breaker ${identifier || ""}] HALF_OPEN -> OPEN (test failed)`,
    );
    circuitState.state = "OPEN";
    circuitState.consecutiveSuccesses = 0;
  } else if (
    circuitState.state === "CLOSED" &&
    circuitState.failures >= FAILURE_THRESHOLD
  ) {
    // Too many failures, open the circuit
    // eslint-disable-next-line no-console
    console.log(
      `[Circuit Breaker ${identifier || ""}] CLOSED -> OPEN (${circuitState.failures} consecutive failures)`,
    );
    circuitState.state = "OPEN";
  }
}

/**
 * Execute a function with circuit breaker protection
 */
export async function executeWithCircuitBreaker<T>(
  fn: () => Promise<T>,
  identifier = "",
): Promise<T> {
  const now = Date.now();

  // Check if we should transition from OPEN to HALF_OPEN
  if (circuitState.state === "OPEN") {
    if (now - circuitState.lastFailureTime > TIMEOUT_MS) {
      // eslint-disable-next-line no-console
      console.log(
        `[Circuit Breaker ${identifier}] OPEN -> HALF_OPEN (timeout elapsed)`,
      );
      circuitState.state = "HALF_OPEN";
      circuitState.consecutiveSuccesses = 0;
    } else {
      // Circuit is still open, fail fast
      const waitTime = Math.ceil(
        (TIMEOUT_MS - (now - circuitState.lastFailureTime)) / 1000,
      );
      throw new Error(
        `Circuit breaker is OPEN. Service temporarily unavailable. Retry in ${waitTime}s.`,
      );
    }
  }

  try {
    const result = await fn();
    onSuccess(identifier);
    return result;
  } catch (error) {
    onFailure(error, identifier);
    throw error;
  }
}

/**
 * Get current circuit state (for debugging/monitoring)
 */
export function getCircuitState(): Readonly<CircuitBreakerState> {
  return { ...circuitState };
}

/**
 * Manually reset circuit breaker (for testing or admin actions)
 */
export function resetCircuitBreaker() {
  circuitState.failures = 0;
  circuitState.lastFailureTime = 0;
  circuitState.state = "CLOSED";
  circuitState.consecutiveSuccesses = 0;
  // eslint-disable-next-line no-console
  console.log("[Circuit Breaker] Manually reset to CLOSED state");
}
