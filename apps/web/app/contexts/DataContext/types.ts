export type QueryStatus = "idle" | "pending" | "success" | "error";

export interface QueryState {
  status: QueryStatus;
  rows: any[];
  totalRows: number;
  error?: string;
  cachedAt?: number; // timestamp when data was cached
  ttl?: number; // time-to-live in ms (from query max_age)
  isFetching: boolean;
  isValidating: boolean; // re-fetching with existing data
}

export interface FetchOptions {
  // Fetch method
  useSSE?: boolean; // true = SSE stream, false = regular fetch (default: true)

  // Pagination
  paginate?: boolean; // enable pagination / infinite scroll
  pageSize?: number; // default: 100
  offset?: number; // default: 0

  // Sorting
  sortBy?: string;
  sortOrder?: "asc" | "desc";

  // Cache control
  force?: boolean; // bypass local cache, force refetch

  // Notifications
  notify?: boolean; // send email notification on complete
  userEmail?: string;
}

export interface SubscriptionCallbacks {
  onData: (data: { rows: any[]; total_rows: number }) => void;
  onError: (error: string) => void;
  onCount?: (totalRows: number) => void;
  onCancelled?: () => void;
}

export interface DataContextValue {
  // Query state
  getQueryState: (queryId: string) => QueryState;

  // Actions
  fetchQuery: (queryId: string, options?: FetchOptions) => void;
  cancelFetch: (queryId: string) => void;
  updateNotification: (
    queryId: string,
    notify: boolean,
    userEmail?: string,
  ) => void;

  // Cache helpers
  isStale: (queryId: string) => boolean;
  hasCachedData: (queryId: string) => boolean;
  invalidateCache: (queryId: string) => void;

  // SSE subscription (for components that need fine-grained control)
  subscribe: (
    queryId: string,
    options: FetchOptions,
    callbacks: SubscriptionCallbacks,
  ) => () => void; // returns unsubscribe function
}

export const DEFAULT_QUERY_STATE: QueryState = {
  status: "idle",
  rows: [],
  totalRows: 0,
  isFetching: false,
  isValidating: false,
};

export const DEFAULT_TTL = 3 * 24 * 60 * 60 * 1000; // 3 days in ms
