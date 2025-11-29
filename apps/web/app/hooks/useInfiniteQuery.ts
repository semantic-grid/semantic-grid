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
  ) =>
  async (key: ReturnType<typeof getKey>): Promise<ApiResponse> => {
    // @ts-ignore
    const [url, id, offset, limit, sortBy, sortOrder] = key;

    console.log(
      "[useInfiniteQuery] Fetcher called - THIS SHOULD ONLY HAPPEN ON BUTTON CLICK!",
      {
        id,
        offset,
        limit,
        sortBy,
        sortOrder,
        notifyOnComplete,
        userEmail,
        stack: new Error().stack,
      },
    );

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
  console.log("[useInfiniteQuery] getKey called", {
    pageIndex,
    id,
    limit,
    sortBy,
    sortOrder,
    hasId: !!id,
    hasSql: !!sql,
  });

  if (!id || !sql) {
    console.log("[useInfiniteQuery] getKey returning null - no id or sql");
    return null;
  }
  if (previousPageData && previousPageData.rows.length === 0) {
    console.log("[useInfiniteQuery] getKey returning null - no more pages");
    return null; // no more pages
  }
  const offset = pageIndex * limit;
  const key = [
    `/api/apegpt/data/sse`,
    id,
    offset,
    limit,
    sortBy,
    sortOrder /* btoa(sql) */,
  ];
  console.log("[useInfiniteQuery] getKey returning key", key);
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
      enabled
        ? (pageIndex, prevData) =>
            getKey(pageIndex, prevData, id!, limit, sortBy, sortOrder, sql)
        : () => null,
      createFetcher(
        dataFetchContext,
        abortController,
        notifyOnComplete,
        userEmail,
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
