import useSWR from "swr";

import type { components } from "@/app/api/apegpt/types.gen";

type AdminRequestsResponse = components["schemas"]["AdminRequestsResponse"];

export const UnauthorizedError = new Error("Unauthorized");

export const useAdminRequests = (
  limit: number = 20,
  offset: number = 0,
  status: string = "Done",
  search?: string,
) => {
  const fetcher = ([url, limit, offset, status, search]: [
    string,
    number,
    number,
    string,
    string | undefined,
  ]) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
      status,
    });
    if (search) {
      params.set("search", search);
    }
    return fetch(`${url}?${params.toString()}`).then((res) => {
      if (res.ok) return res.json();
      throw UnauthorizedError;
    });
  };

  const { data, error, isLoading, mutate } = useSWR<AdminRequestsResponse>(
    ["/api/apegpt/admin/requests", limit, offset, status, search],
    fetcher,
    {
      shouldRetryOnError: false,
      revalidateOnFocus: false,
      revalidateOnMount: true,
      revalidateOnReconnect: false,
      refreshWhenOffline: false,
      refreshWhenHidden: false,
      refreshInterval: 0,
    },
  );

  return {
    data: data?.requests,
    total: data?.total ?? 0,
    error,
    isLoading,
    mutate,
  };
};
