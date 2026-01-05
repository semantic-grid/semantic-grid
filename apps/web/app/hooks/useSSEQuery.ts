import { useCallback,useEffect, useRef, useState } from "react";

export const UnauthorizedError = new Error("Unauthorized");

type SSEQueryState = {
  rows: any[];
  totalRows: number;
  isLoading: boolean;
  isCounting: boolean;
  error: Error | null;
  elapsed: number;
};

type SSEEventData =
  | { event: "started"; status: "started"; task_id: string; query_id: string }
  | {
      event: "count";
      status: "counting_complete";
      query_id: string;
      total_rows: number;
    }
  | { event: "progress"; status: "running"; elapsed: number }
  | {
      event: "data";
      status: "success";
      query_id: string;
      rows: any[];
      total_rows: number;
      limit: number;
      offset: number;
    }
  | { event: "error"; status: "error"; error: string };

export const useSSEQuery = ({
  id,
  sql,
  limit = 100,
  offset = 0,
  sortBy,
  sortOrder,
  enabled = true,
}: {
  id?: string;
  sql?: string;
  limit?: number;
  offset?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  enabled?: boolean;
}) => {
  const [state, setState] = useState<SSEQueryState>({
    rows: [],
    totalRows: 0,
    isLoading: false,
    isCounting: false,
    error: null,
    elapsed: 0,
  });

  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!id || !sql || !enabled) return;

    // Close existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setState((prev) => ({
      ...prev,
      isLoading: true,
      isCounting: false,
      error: null,
      rows: [],
      elapsed: 0,
    }));

    // Build URL with query params
    const params = new URLSearchParams();
    if (limit !== undefined) params.append("limit", String(limit));
    if (offset !== undefined) params.append("offset", String(offset));
    if (sortBy) params.append("sort_by", sortBy);
    if (sortOrder) params.append("sort_order", sortOrder);

    const url = `/api/apegpt/data/sse/${id}?${params.toString()}`;
    const eventSource = new EventSource(url);

    eventSource.addEventListener("auth_error", (e) => {
      const data = JSON.parse(e.data);
      console.log("SSE auth error, redirecting to login");
      eventSource.close();
      if (data.redirect) {
        window.location.href = data.redirect;
      }
    });

    eventSource.addEventListener("started", (e) => {
      const data = JSON.parse(e.data);
      console.log("SSE started:", data);
    });

    eventSource.addEventListener("count", (e) => {
      const data = JSON.parse(e.data);
      console.log("SSE count:", data);
      setState((prev) => ({
        ...prev,
        totalRows: data.total_rows,
        isCounting: true,
      }));
    });

    eventSource.addEventListener("progress", (e) => {
      const data = JSON.parse(e.data);
      console.log("SSE progress:", data);
      setState((prev) => ({
        ...prev,
        elapsed: data.elapsed,
      }));
    });

    eventSource.addEventListener("data", (e) => {
      const data = JSON.parse(e.data);
      console.log("SSE data:", data);
      setState((prev) => ({
        ...prev,
        rows: data.rows,
        totalRows: data.total_rows,
        isLoading: false,
        isCounting: false,
      }));
      eventSource.close();
    });

    eventSource.addEventListener("error", (e: any) => {
      const data = e.data ? JSON.parse(e.data) : { error: "Unknown error" };
      console.error("SSE error:", data);
      setState((prev) => ({
        ...prev,
        error: new Error(data.error || "Failed to fetch data"),
        isLoading: false,
        isCounting: false,
      }));
      eventSource.close();
    });

    eventSource.onerror = (err) => {
      console.error("EventSource error:", err);
      setState((prev) => ({
        ...prev,
        error: new Error("Connection error"),
        isLoading: false,
        isCounting: false,
      }));
      eventSource.close();
    };

    eventSourceRef.current = eventSource;
  }, [id, sql, limit, offset, sortBy, sortOrder, enabled]);

  useEffect(() => {
    connect();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [connect]);

  const refetch = useCallback(() => {
    connect();
  }, [connect]);

  return {
    ...state,
    refetch,
  };
};
