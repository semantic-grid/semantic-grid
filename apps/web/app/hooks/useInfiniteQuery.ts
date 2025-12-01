import useSWRInfinite from "swr/infinite";

import { useDataFetch } from "@/app/contexts/DataFetchContext";

export const UnauthorizedError = new Error("Unauthorized");

type ApiResponse = {
  total_rows: number;
  rows: any[];
};

const createFetcher =
  (
    dataFetchContext: ReturnType<typeof useDataFetch>,
    abortController: AbortController,
    notifyOnComplete?: boolean,
    userEmail?: string,
    enabled?: boolean,
  ) =>
  async (key: ReturnType<typeof getKey>): Promise<ApiResponse> => {
    // @ts-ignore
    const [url, id, offset, limit, sortBy, sortOrder] = key;

    // If not enabled, return a promise that never resolves
    // This prevents the fetch but allows SWR to check cache
    if (!enabled) {
      console.log("[useInfiniteQuery] Fetcher blocked - enabled=false");
      return new Promise(() => {}); // Never resolves, SWR will show cached data if available
    }

    console.log("[useInfiniteQuery] Fetcher called - User requested fetch!", {
      id,
      offset,
      limit,
      sortBy,
      sortOrder,
      notifyOnComplete,
      userEmail,
    });

    return new Promise<ApiResponse>((resolve, reject) => {
      const unsubscribe = dataFetchContext.subscribe(
        {
          id,
          limit: limit ?? 100,
          offset: offset ?? 0,
          sortBy,
          sortOrder,
          notifyOnComplete,
          userEmail,
        },
        {
          onData: (data) => {
            resolve(data);
            unsubscribe();
          },
          onError: (error) => {
            reject(new Error(error));
            unsubscribe();
          },
        },
      );

      // Handle abort signal
      abortController.signal.addEventListener("abort", () => {
        unsubscribe();
        reject(new Error("Aborted"));
      });
    });
  };

const getKey = (
  pageIndex: number,
  previousPageData: ApiResponse | null,
  id: string,
  limit: number,
  sortBy?: string,
  sortOrder?: "asc" | "desc",
  sql?: string,
):
  | [string, string, number, number, string?, ("asc" | "desc")?, string?]
  | null => {
  // Only return null if we don't have the minimum required data
  if (!id || !sql) {
    return null;
  }

  // Stop pagination if previous page was empty
  if (previousPageData && previousPageData.rows.length === 0) {
    return null; // no more pages
  }

  const offset = pageIndex * limit;
  const key = [`/api/apegpt/data/sse`, id, offset, limit, sortBy, sortOrder];
  return key;
};

export const useInfiniteQuery = ({
  id,
  sql,
  limit = 100,
  sortBy,
  sortOrder,
  notifyOnComplete = false,
  userEmail,
  enabled = false,
}: {
  id?: string;
  sql?: string;
  limit?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  notifyOnComplete?: boolean;
  userEmail?: string;
  enabled?: boolean;
}) => {
  // console.log("useInfiniteQuery req", id, sortBy, sortOrder);
  const dataFetchContext = useDataFetch();
  const abortController = new AbortController();

  const { data, error, isLoading, size, setSize, mutate, isValidating } =
    useSWRInfinite<ApiResponse>(
      (pageIndex, prevData) =>
        getKey(pageIndex, prevData, id!, limit, sortBy, sortOrder, sql),
      createFetcher(
        dataFetchContext,
        abortController,
        notifyOnComplete,
        userEmail,
        enabled, // Pass enabled to fetcher
      ),
      {
        revalidateIfStale: false,
        refreshInterval: 0,
        revalidateOnFocus: false,
        revalidateOnMount: false,
        revalidateOnReconnect: false,
        shouldRetryOnError: false,
        keepPreviousData: true, // Keep showing old data while fetching new data
      },
    );

  // console.log("useInfiniteQuery res", data, size, isLoading, isValidating);
  const rows = data?.flatMap((page) => page.rows) ?? [];
  const totalRows = data?.[0]?.total_rows ?? 0;
  const isReachingEnd = rows.length >= totalRows;

  return {
    rows,
    totalRows,
    error,
    isLoading,
    // isLoading: isLoading && size === 1,
    // isFetchingMore: isLoading && size > 1,
    isReachingEnd,
    size,
    setSize,
    mutate,
    isValidating,
    abortController,
  };
};
