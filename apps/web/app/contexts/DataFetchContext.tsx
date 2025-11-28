"use client";

import React, {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
} from "react";

type FetchParams = {
  id: string;
  limit: number;
  offset: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  notifyOnComplete?: boolean;
  userEmail?: string;
};

type SubscriptionCallbacks = {
  onData: (data: { rows: any[]; total_rows: number }) => void;
  onError: (error: string) => void;
  onCount?: (totalRows: number) => void;
};

type Subscription = {
  id: string;
  callbacks: SubscriptionCallbacks;
};

type FetchState = {
  eventSource: EventSource;
  status:
    | "connecting"
    | "counting"
    | "fetching"
    | "complete"
    | "error"
    | "workers_busy";
  totalRows?: number;
  data?: { rows: any[]; total_rows: number };
  error?: string;
  subscriptions: Map<string, Subscription>;
};

interface DataFetchContextValue {
  subscribe: (
    params: FetchParams,
    callbacks: SubscriptionCallbacks,
  ) => () => void;
  hasCache: (params: FetchParams) => boolean;
  getCacheStatus: (params: FetchParams) => "none" | "complete" | "error";
}

const DataFetchContext = createContext<DataFetchContextValue | undefined>(
  undefined,
);

export const useDataFetch = () => {
  const context = useContext(DataFetchContext);
  if (!context) {
    throw new Error("useDataFetch must be used within DataFetchProvider");
  }
  return context;
};

export const DataFetchProvider = ({ children }: { children: ReactNode }) => {
  // Map of URL -> FetchState
  const fetchMapRef = useRef<Map<string, FetchState>>(new Map());
  // Cleanup timers for unused fetches
  const cleanupTimersRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

  const buildUrl = useCallback((params: FetchParams): string => {
    const queryParams = new URLSearchParams();
    queryParams.append("limit", String(params.limit));
    queryParams.append("offset", String(params.offset));
    if (params.sortBy) queryParams.append("sort_by", params.sortBy);
    if (params.sortOrder) queryParams.append("sort_order", params.sortOrder);
    if (params.notifyOnComplete)
      queryParams.append("notify_on_complete", "true");
    if (params.userEmail) queryParams.append("user_email", params.userEmail);
    return `/api/apegpt/data/sse/${params.id}?${queryParams.toString()}`;
  }, []);

  const createEventSource = useCallback(
    (url: string, fetchState: FetchState) => {
      const eventSource = new EventSource(url);

      eventSource.addEventListener("reconnected", (e) => {
        const data = JSON.parse(e.data);
        fetchState.status = "fetching";
        console.log("Reconnected to running query:", data.message);
      });

      eventSource.addEventListener("workers_busy", (e) => {
        const data = JSON.parse(e.data);
        fetchState.status = "workers_busy";
        console.log("Workers busy:", data.message);
      });

      eventSource.addEventListener("count", (e) => {
        const data = JSON.parse(e.data);
        fetchState.status = "counting";
        fetchState.totalRows = data.total_rows;

        // Notify all subscribers about count
        fetchState.subscriptions.forEach((sub) => {
          sub.callbacks.onCount?.(data.total_rows);
        });
      });

      eventSource.addEventListener("data", (e) => {
        const data = JSON.parse(e.data);
        fetchState.status = "complete";
        fetchState.data = {
          rows: data.rows,
          total_rows: data.total_rows,
        };

        // Notify all subscribers
        fetchState.subscriptions.forEach((sub) => {
          sub.callbacks.onData(fetchState.data!);
        });

        // Close the EventSource after successful delivery
        eventSource.close();
      });

      eventSource.addEventListener("error", (e: any) => {
        const errorData = e.data
          ? JSON.parse(e.data)
          : { error: "Unknown error" };
        fetchState.status = "error";
        fetchState.error = errorData.error || "Failed to fetch data";

        // Notify all subscribers
        fetchState.subscriptions.forEach((sub) => {
          sub.callbacks.onError(fetchState.error!);
        });

        eventSource.close();
      });

      eventSource.onerror = () => {
        if (eventSource.readyState === EventSource.CLOSED) {
          fetchState.status = "error";
          fetchState.error = "Connection closed";

          // Notify all subscribers
          fetchState.subscriptions.forEach((sub) => {
            sub.callbacks.onError("Connection closed");
          });
        }
      };

      return eventSource;
    },
    [],
  );

  const hasCache = useCallback(
    (params: FetchParams): boolean => {
      const url = buildUrl(params);
      const fetchState = fetchMapRef.current.get(url);
      return (
        !!fetchState &&
        (fetchState.status === "complete" || fetchState.status === "error")
      );
    },
    [buildUrl],
  );

  const getCacheStatus = useCallback(
    (params: FetchParams): "none" | "complete" | "error" => {
      const url = buildUrl(params);
      const fetchState = fetchMapRef.current.get(url);
      if (!fetchState) return "none";
      if (fetchState.status === "complete") return "complete";
      if (fetchState.status === "error") return "error";
      return "none";
    },
    [buildUrl],
  );

  const subscribe = useCallback(
    (params: FetchParams, callbacks: SubscriptionCallbacks): (() => void) => {
      const url = buildUrl(params);
      const subscriptionId = `${url}-${Date.now()}-${Math.random()}`;

      // Cancel any pending cleanup for this URL
      const cleanupTimer = cleanupTimersRef.current.get(url);
      if (cleanupTimer) {
        clearTimeout(cleanupTimer);
        cleanupTimersRef.current.delete(url);
      }

      let fetchState = fetchMapRef.current.get(url);

      if (!fetchState) {
        // Create new fetch state and EventSource
        fetchState = {
          eventSource: null as any,
          status: "connecting",
          subscriptions: new Map(),
        };
        fetchMapRef.current.set(url, fetchState);

        // Create EventSource
        fetchState.eventSource = createEventSource(url, fetchState);
      }

      // Add subscription
      fetchState.subscriptions.set(subscriptionId, {
        id: subscriptionId,
        callbacks,
      });

      // If fetch already completed, notify immediately
      if (fetchState.status === "complete" && fetchState.data) {
        callbacks.onData(fetchState.data);
      } else if (fetchState.status === "error" && fetchState.error) {
        callbacks.onError(fetchState.error);
      } else if (fetchState.totalRows !== undefined) {
        callbacks.onCount?.(fetchState.totalRows);
      }

      // Return unsubscribe function
      return () => {
        const state = fetchMapRef.current.get(url);
        if (!state) return;

        // Remove subscription
        state.subscriptions.delete(subscriptionId);

        // If no more subscribers, schedule cleanup
        if (state.subscriptions.size === 0) {
          const timer = setTimeout(() => {
            const currentState = fetchMapRef.current.get(url);
            if (currentState && currentState.subscriptions.size === 0) {
              // Close EventSource and remove from map
              currentState.eventSource.close();
              fetchMapRef.current.delete(url);
              cleanupTimersRef.current.delete(url);
            }
          }, 30000); // 30 second grace period

          cleanupTimersRef.current.set(url, timer);
        }
      };
    },
    [buildUrl, createEventSource],
  );

  return (
    <DataFetchContext.Provider value={{ subscribe, hasCache, getCacheStatus }}>
      {children}
    </DataFetchContext.Provider>
  );
};
