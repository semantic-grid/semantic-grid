"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  DEFAULT_QUERY_STATE,
  DEFAULT_TTL,
  type DataContextValue,
  type FetchOptions,
  type QueryState,
  type SubscriptionCallbacks,
} from "./types";

const DataContext = createContext<DataContextValue | undefined>(undefined);

// Helper to extract queryId from SWR cache key
// Key formats:
//   $inf$@"/api/apegpt/data/sse","queryId",... (SWR infinite)
//   @"/api/apegpt/data/sse","queryId",... (regular SWR)
const parseSwrCacheKey = (key: string): string | null => {
  if (!key.includes("/api/apegpt/data/sse")) return null;

  // Extract UUID from key
  const match = key.match(/"([a-f0-9-]{36})"/);
  return match?.[1] ?? null;
};

// Extract rows and totalRows from various cache value formats
const extractDataFromCacheValue = (
  value: unknown,
): { rows: any[]; totalRows: number } | null => {
  if (!value || typeof value !== "object") return null;

  // Format 1: SWR infinite - array of pages [{rows, total_rows}, ...]
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    const firstPage = value[0];
    if (firstPage?.rows) {
      return {
        rows: firstPage.rows,
        totalRows: firstPage.total_rows ?? firstPage.rows.length,
      };
    }
    return null;
  }

  // Format 2: Direct object with data.rows
  const obj = value as Record<string, unknown>;
  if (obj.data && typeof obj.data === "object") {
    const data = obj.data as Record<string, unknown>;
    if (Array.isArray(data.rows)) {
      return {
        rows: data.rows,
        totalRows: (data.total_rows as number) ?? data.rows.length,
      };
    }
  }

  // Format 3: Direct object with rows
  if (Array.isArray(obj.rows)) {
    return {
      rows: obj.rows,
      totalRows: (obj.total_rows as number) ?? obj.rows.length,
    };
  }

  return null;
};

// Hydrate query states from SWR localStorage cache
const hydrateFromLocalStorage = (): Map<string, QueryState> => {
  const states = new Map<string, QueryState>();

  if (typeof window === "undefined") return states;

  try {
    const rawCache = localStorage.getItem("app-cache");
    if (!rawCache) {
      console.log("[DataContext] No app-cache in localStorage");
      return states;
    }

    const cacheData: Array<[string, any]> = JSON.parse(rawCache);
    console.log(`[DataContext] Found ${cacheData.length} cache entries`);

    for (const [key, value] of cacheData) {
      if (typeof key !== "string") continue;

      const queryId = parseSwrCacheKey(key);
      if (!queryId) continue;

      const extracted = extractDataFromCacheValue(value);
      if (!extracted || extracted.rows.length === 0) continue;

      // Only hydrate if we don't already have this query or if this has more data
      const existing = states.get(queryId);
      if (!existing || extracted.rows.length > existing.rows.length) {
        states.set(queryId, {
          status: "success",
          rows: extracted.rows,
          totalRows: extracted.totalRows,
          isFetching: false,
          isValidating: false,
          cachedAt: Date.now(),
        });
        console.log(
          `[DataContext] Hydrated query ${queryId}: ${extracted.rows.length} rows`,
        );
      }
    }
  } catch (error) {
    console.warn("[DataContext] Failed to hydrate from localStorage:", error);
  }

  return states;
};

export const useData = () => {
  const context = useContext(DataContext);
  if (!context) {
    throw new Error("useData must be used within DataProvider");
  }
  return context;
};

// Helper to build SSE URL
const buildSSEUrl = (queryId: string, options: FetchOptions): string => {
  const params = new URLSearchParams();
  if (options.limit) params.append("limit", String(options.limit));
  if (options.offset) params.append("offset", String(options.offset));
  if (options.sortBy) params.append("sort_by", options.sortBy);
  if (options.sortOrder) params.append("sort_order", options.sortOrder);
  if (options.force) params.append("force", "true");
  if (options.notify) params.append("notify_on_complete", "true");
  if (options.userEmail) params.append("user_email", options.userEmail);
  return `/api/apegpt/data/sse/${queryId}?${params.toString()}`;
};

// Helper to build cache key
const buildCacheKey = (queryId: string, options: FetchOptions): string => {
  return `${queryId}:${options.limit || 100}:${options.offset || 0}:${options.sortBy || ""}:${options.sortOrder || "asc"}`;
};

interface FetchState {
  eventSource: EventSource | null;
  status:
    | "connecting"
    | "counting"
    | "fetching"
    | "complete"
    | "error"
    | "cancelled";
  subscribers: Map<string, SubscriptionCallbacks>;
}

export const DataProvider = ({ children }: { children: ReactNode }) => {
  // Query states by queryId - initialized empty, hydrated on mount
  const [queryStates, setQueryStates] = useState<Map<string, QueryState>>(
    () => new Map(),
  );

  // Track if we've hydrated from localStorage
  const hasHydratedRef = useRef(false);

  // Hydrate from localStorage on mount (client-side only)
  useEffect(() => {
    if (hasHydratedRef.current) return;
    hasHydratedRef.current = true;

    const hydrated = hydrateFromLocalStorage();
    if (hydrated.size > 0) {
      console.log(
        `[DataContext] Hydrated ${hydrated.size} queries from localStorage`,
      );
      setQueryStates(hydrated);
    }
  }, []);

  // Active fetches by cache key
  const fetchStatesRef = useRef<Map<string, FetchState>>(new Map());

  // Cleanup timers
  const cleanupTimersRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

  // Get query state (returns default if not found)
  const getQueryState = useCallback(
    (queryId: string): QueryState => {
      return queryStates.get(queryId) || DEFAULT_QUERY_STATE;
    },
    [queryStates],
  );

  // Update query state
  const updateQueryState = useCallback(
    (queryId: string, updates: Partial<QueryState>) => {
      setQueryStates((prev) => {
        const newMap = new Map(prev);
        const current = newMap.get(queryId) || DEFAULT_QUERY_STATE;
        newMap.set(queryId, { ...current, ...updates });
        return newMap;
      });
    },
    [],
  );

  // Check if data is stale based on TTL
  const isStale = useCallback(
    (queryId: string): boolean => {
      const state = queryStates.get(queryId);
      if (!state || !state.cachedAt) return true;
      const ttl = state.ttl || DEFAULT_TTL;
      return Date.now() - state.cachedAt > ttl;
    },
    [queryStates],
  );

  // Check if cached data exists
  const hasCachedData = useCallback(
    (queryId: string): boolean => {
      const state = queryStates.get(queryId);
      return !!state && state.rows.length > 0;
    },
    [queryStates],
  );

  // Invalidate cache for a query
  const invalidateCache = useCallback((queryId: string) => {
    setQueryStates((prev) => {
      const newMap = new Map(prev);
      newMap.delete(queryId);
      return newMap;
    });
  }, []);

  // Create EventSource and set up listeners
  const createEventSource = useCallback(
    (
      url: string,
      cacheKey: string,
      queryId: string,
      fetchState: FetchState,
    ) => {
      const eventSource = new EventSource(url);
      fetchState.eventSource = eventSource;

      eventSource.addEventListener("connected", (e) => {
        console.log("[DataContext] Connected:", e.data);
        fetchState.status = "fetching";
        updateQueryState(queryId, { isFetching: true, status: "pending" });
      });

      eventSource.addEventListener("reconnected", (e) => {
        const data = JSON.parse(e.data);
        console.log("[DataContext] Reconnected:", data.message);
        fetchState.status = "fetching";
      });

      eventSource.addEventListener("workers_busy", (e) => {
        const data = JSON.parse(e.data);
        console.log("[DataContext] Workers busy:", data.message);
      });

      eventSource.addEventListener("count", (e) => {
        const data = JSON.parse(e.data);
        fetchState.status = "counting";

        // Notify subscribers
        fetchState.subscribers.forEach((sub) => {
          sub.onCount?.(data.total_rows);
        });

        updateQueryState(queryId, { totalRows: data.total_rows });
      });

      eventSource.addEventListener("data", (e) => {
        const data = JSON.parse(e.data);
        fetchState.status = "complete";

        // Update query state
        updateQueryState(queryId, {
          status: "success",
          rows: data.rows,
          totalRows: data.total_rows,
          isFetching: false,
          isValidating: false,
          cachedAt: Date.now(),
          error: undefined,
        });

        // Notify subscribers
        fetchState.subscribers.forEach((sub) => {
          sub.onData(data);
        });

        // Close connection
        eventSource.close();
        fetchStatesRef.current.delete(cacheKey);
      });

      eventSource.addEventListener("error", (e: any) => {
        const errorData = e.data
          ? JSON.parse(e.data)
          : { error: "Unknown error" };
        fetchState.status = "error";

        updateQueryState(queryId, {
          status: "error",
          error: errorData.error || "Failed to fetch data",
          isFetching: false,
          isValidating: false,
        });

        // Notify subscribers
        fetchState.subscribers.forEach((sub) => {
          sub.onError(errorData.error || "Failed to fetch data");
        });

        eventSource.close();
        fetchStatesRef.current.delete(cacheKey);
      });

      eventSource.addEventListener("cancelled", (e) => {
        fetchState.status = "cancelled";

        updateQueryState(queryId, {
          status: "idle",
          isFetching: false,
          isValidating: false,
        });

        // Notify subscribers
        fetchState.subscribers.forEach((sub) => {
          sub.onCancelled?.();
        });

        eventSource.close();
        fetchStatesRef.current.delete(cacheKey);
      });

      eventSource.onerror = () => {
        if (eventSource.readyState === EventSource.CLOSED) {
          console.error("[DataContext] SSE connection closed");

          if (
            fetchState.status !== "complete" &&
            fetchState.status !== "cancelled"
          ) {
            updateQueryState(queryId, {
              status: "error",
              error: "Connection closed",
              isFetching: false,
              isValidating: false,
            });

            fetchState.subscribers.forEach((sub) => {
              sub.onError("Connection closed");
            });
          }

          fetchStatesRef.current.delete(cacheKey);
        }
      };

      return eventSource;
    },
    [updateQueryState],
  );

  // Subscribe to data fetch
  const subscribe = useCallback(
    (
      queryId: string,
      sql: string,
      options: FetchOptions,
      callbacks: SubscriptionCallbacks,
    ): (() => void) => {
      const cacheKey = buildCacheKey(queryId, options);
      const subscriptionId = `${cacheKey}-${Date.now()}-${Math.random()}`;

      console.log("[DataContext] Subscribe:", { queryId, cacheKey });

      // Cancel any pending cleanup
      const cleanupTimer = cleanupTimersRef.current.get(cacheKey);
      if (cleanupTimer) {
        clearTimeout(cleanupTimer);
        cleanupTimersRef.current.delete(cacheKey);
      }

      let fetchState = fetchStatesRef.current.get(cacheKey);

      if (!fetchState) {
        // Create new fetch state
        fetchState = {
          eventSource: null,
          status: "connecting",
          subscribers: new Map(),
        };
        fetchStatesRef.current.set(cacheKey, fetchState);

        // Determine if this is a revalidation (has existing data)
        const hasData = hasCachedData(queryId);
        updateQueryState(queryId, {
          isFetching: !hasData,
          isValidating: hasData,
          status: "pending",
        });

        // Create EventSource
        const url = buildSSEUrl(queryId, options);
        createEventSource(url, cacheKey, queryId, fetchState);
      }

      // Add subscriber
      fetchState.subscribers.set(subscriptionId, callbacks);

      // If already complete, notify immediately
      const state = queryStates.get(queryId);
      if (fetchState.status === "complete" && state) {
        callbacks.onData({ rows: state.rows, total_rows: state.totalRows });
      } else if (fetchState.status === "error" && state?.error) {
        callbacks.onError(state.error);
      }

      // Return unsubscribe function
      return () => {
        const currentFetchState = fetchStatesRef.current.get(cacheKey);
        if (!currentFetchState) return;

        currentFetchState.subscribers.delete(subscriptionId);

        // If no more subscribers, schedule cleanup
        if (currentFetchState.subscribers.size === 0) {
          const timer = setTimeout(() => {
            const state = fetchStatesRef.current.get(cacheKey);
            if (state && state.subscribers.size === 0) {
              state.eventSource?.close();
              fetchStatesRef.current.delete(cacheKey);
              cleanupTimersRef.current.delete(cacheKey);
            }
          }, 30000); // 30 second grace period

          cleanupTimersRef.current.set(cacheKey, timer);
        }
      };
    },
    [createEventSource, hasCachedData, queryStates, updateQueryState],
  );

  // Fetch query data
  const fetchQuery = useCallback(
    (queryId: string, sql: string, options: FetchOptions = {}) => {
      console.log("[DataContext] fetchQuery:", { queryId, options });

      // If force, invalidate local cache first
      if (options.force) {
        invalidateCache(queryId);
      }

      const cacheKey = buildCacheKey(queryId, options);

      // Check if already fetching
      if (fetchStatesRef.current.has(cacheKey)) {
        console.log("[DataContext] Already fetching:", cacheKey);
        return;
      }

      // Start fetch via subscribe (will handle SSE connection)
      const unsubscribe = subscribe(queryId, sql, options, {
        onData: () => {
          // Data will be in queryState
          unsubscribe();
        },
        onError: () => {
          unsubscribe();
        },
      });
    },
    [invalidateCache, subscribe],
  );

  // Cancel fetch
  const cancelFetch = useCallback(
    async (queryId: string) => {
      console.log("[DataContext] cancelFetch:", queryId);

      // Find all fetch states for this queryId
      fetchStatesRef.current.forEach((state, key) => {
        if (key.startsWith(queryId)) {
          state.eventSource?.close();
          fetchStatesRef.current.delete(key);
        }
      });

      // Call backend to cancel
      try {
        await fetch(`/api/apegpt/data/${queryId}`, {
          method: "DELETE",
        });
      } catch (error) {
        console.error("[DataContext] Failed to cancel on backend:", error);
      }

      updateQueryState(queryId, {
        status: "idle",
        isFetching: false,
        isValidating: false,
      });
    },
    [updateQueryState],
  );

  // Update notification settings
  const updateNotification = useCallback(
    async (queryId: string, notify: boolean, userEmail?: string) => {
      console.log("[DataContext] updateNotification:", { queryId, notify });

      try {
        await fetch(`/api/apegpt/data/${queryId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ notify, user_email: userEmail }),
        });
      } catch (error) {
        console.error("[DataContext] Failed to update notification:", error);
      }
    },
    [],
  );

  const value = useMemo(
    (): DataContextValue => ({
      getQueryState,
      fetchQuery,
      cancelFetch,
      updateNotification,
      isStale,
      hasCachedData,
      invalidateCache,
      subscribe,
    }),
    [
      getQueryState,
      fetchQuery,
      cancelFetch,
      updateNotification,
      isStale,
      hasCachedData,
      invalidateCache,
      subscribe,
    ],
  );

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
};

export * from "./types";
