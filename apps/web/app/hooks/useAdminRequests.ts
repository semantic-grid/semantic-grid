import useSWR from "swr";

import type { components } from "@/app/api/apegpt/types.gen";

type AdminRequestsResponse = components["schemas"]["AdminRequestsResponse"];
type PatchAdminRequestModel = components["schemas"]["PatchAdminRequestModel"];
export type TraceSummary = components["schemas"]["TraceSummary"];
export type GetTraceStepModel = components["schemas"]["GetTraceStepModel"];
export type GetRequestTraceModel =
  components["schemas"]["GetRequestTraceModel"];
export type GetPromptVersionModel =
  components["schemas"]["GetPromptVersionModel"];

export const UnauthorizedError = new Error("Unauthorized");

export const useAdminRequests = (
  limit: number = 20,
  offset: number = 0,
  status: string = "Done",
  search?: string,
  hasFeedback: boolean = false,
  isTest?: boolean | null,
  isFixed?: boolean | null,
) => {
  const fetcher = ([
    url,
    limit,
    offset,
    status,
    search,
    hasFeedback,
    isTest,
    isFixed,
  ]: [
    string,
    number,
    number,
    string,
    string | undefined,
    boolean,
    boolean | null | undefined,
    boolean | null | undefined,
  ]) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    // Only add status param if not "All" - backend treats missing status as all
    if (status && status !== "All") {
      params.set("status", status);
    }
    if (search) {
      params.set("search", search);
    }
    if (hasFeedback) {
      params.set("has_feedback", "true");
    }
    if (isTest !== null && isTest !== undefined) {
      params.set("is_test", String(isTest));
    }
    if (isFixed !== null && isFixed !== undefined) {
      params.set("is_fixed", String(isFixed));
    }
    return fetch(`${url}?${params.toString()}`).then((res) => {
      if (res.ok) return res.json();
      throw UnauthorizedError;
    });
  };

  const { data, error, isLoading, mutate } = useSWR<AdminRequestsResponse>(
    [
      "/api/apegpt/admin/requests",
      limit,
      offset,
      status,
      search,
      hasFeedback,
      isTest,
      isFixed,
    ],
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

export const updateAdminRequest = async (
  requestId: string,
  patch: PatchAdminRequestModel,
): Promise<void> => {
  const res = await fetch(`/api/apegpt/admin/requests/${requestId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    throw new Error("Failed to update request");
  }
};

export const useRequestTrace = (requestId: string | null) => {
  const fetcher = (url: string) =>
    fetch(url).then((res) => {
      if (res.ok) return res.json();
      if (res.status === 404) return null;
      throw new Error("Failed to fetch trace");
    });

  const { data, error, isLoading } = useSWR<GetRequestTraceModel | null>(
    requestId ? `/api/apegpt/admin/traces/${requestId}` : null,
    fetcher,
    {
      shouldRetryOnError: false,
      revalidateOnFocus: false,
    },
  );

  return { trace: data, error, isLoading };
};

export const fetchPromptVersion = async (
  versionId: string,
): Promise<GetPromptVersionModel> => {
  const res = await fetch(`/api/apegpt/admin/prompt-versions/${versionId}`);
  if (!res.ok) {
    throw new Error("Failed to fetch prompt version");
  }
  return res.json();
};

// Query Explorer types and hooks
type QueryExplorerResponse = components["schemas"]["QueryExplorerResponse"];
export type QueryExplorerItem = components["schemas"]["QueryExplorerItem"];
export type QueryExplorerRequestSummary =
  components["schemas"]["QueryExplorerRequestSummary"];

export const useQueryExplorer = (
  limit: number = 50,
  offset: number = 0,
  search?: string,
) => {
  const fetcher = ([url, limit, offset, search]: [
    string,
    number,
    number,
    string | undefined,
  ]) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (search) {
      params.set("search", search);
    }
    return fetch(`${url}?${params.toString()}`).then((res) => {
      if (res.ok) return res.json();
      throw UnauthorizedError;
    });
  };

  const { data, error, isLoading, mutate } = useSWR<QueryExplorerResponse>(
    ["/api/apegpt/admin/query-explorer", limit, offset, search],
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
    data: data?.queries,
    total: data?.total ?? 0,
    error,
    isLoading,
    mutate,
  };
};
