import { useCallback, useMemo, useState } from "react";
import useSWR, { unstable_serialize, useSWRConfig } from "swr";

import { useDataFetch } from "@/app/contexts/DataFetchContext";

export const UnauthorizedError = new Error("Unauthorized");

const LS_KEY = "app-cache-freshness";

type Freshness = Record<string, number>;

const serializeKey = (key: any) => (key ? unstable_serialize(key) : null);

const readFreshness = (): Freshness => {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || "{}") as Freshness;
  } catch {
    return {};
  }
};

export const setFreshness = (key: string, ts = Date.now()) => {
  const f = readFreshness();
  f[key] = ts;
  localStorage.setItem(LS_KEY, JSON.stringify(f));
};

export const getFreshness = (key: string): number | null => {
  const f = readFreshness();
  return typeof f[key] === "number" ? f[key] : null;
};

const createFetcher = (dataFetchContext: ReturnType<typeof useDataFetch>) => {
  return async ([url, id, limit, offset, sortBy, sortOrder]: [
    url: string,
    id: string,
    limit?: number,
    offset?: number,
    sortBy?: string,
    sortOrder?: "asc" | "desc",
  ]) => {
    return new Promise<{ rows: any[]; total_rows: number }>(
      (resolve, reject) => {
        const unsubscribe = dataFetchContext.subscribe(
          {
            id,
            limit: limit ?? 100,
            offset: offset ?? 0,
            sortBy,
            sortOrder,
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
      },
    );
  };
};

// Remove non-ASCII characters to avoid 400 error from API
const sanitize = (str: string) => str.replace(/[^\x20-\x7E]+/g, "");

export const useQuery = ({
  id,
  sql,
  limit,
  offset,
  sortBy,
  sortOrder,
  enabled = true,
}: {
  id?: string;
  sql?: string; // not used
  limit?: number;
  offset?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  enabled?: boolean;
}) => {
  const { mutate: mutateCache } = useSWRConfig();
  const [force, setForce] = useState<boolean>(false);
  const dataFetchContext = useDataFetch();

  // console.log("useQuery", id, limit, offset, sortBy, sortOrder);
  // const sqlHash = sql ? btoa(sanitize(sql)) : "";
  const key =
    enabled && id
      ? [`/api/apegpt/data/sse`, id, limit, offset, sortBy, sortOrder]
      : null;

  const fetcher = useMemo(
    () => createFetcher(dataFetchContext),
    [dataFetchContext],
  );

  const { data, error, isLoading, isValidating, mutate } = useSWR(
    key,
    fetcher,
    {
      keepPreviousData: true, // Keep showing old data while fetching new data
      shouldRetryOnError: false,
      revalidateOnFocus: false,
      revalidateOnMount: true,
      revalidateOnReconnect: false,
      refreshWhenOffline: false,
      refreshWhenHidden: false,
      refreshInterval: 0,
      onSuccess(data, k, c) {
        // console.log("useQuery onSuccess", id, k);
        if (k) setFreshness(k as string);
      },
    },
  );

  const fetchedAt = key ? getFreshness(serializeKey(key) as string) : null;

  const refresh = useCallback(async () => {
    if (!key) return;
    setForce(true);
    try {
      await mutate();
    } finally {
      setForce(false);
      setFreshness(serializeKey(key) as string);
    }
  }, [key]);

  const isRefreshing = useMemo(
    () => force || isValidating,
    [isValidating, force],
  );

  // Show loading only when there's no data yet (initial fetch)
  const isInitialLoading = useMemo(() => isLoading && !data, [isLoading, data]);

  return {
    data,
    error,
    isLoading: isInitialLoading, // Only true during initial fetch with no data
    isValidating,
    isRefreshing,
    mutate,
    mutateCache,
    refresh,
    fetchedAt,
  };
};
