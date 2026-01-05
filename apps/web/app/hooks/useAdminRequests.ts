import useSWR from "swr";

import type { components } from "@/app/api/apegpt/types.gen";

export type GetRequestModel = components["schemas"]["GetRequestModel"];
export type GetQueryModel = components["schemas"]["GetQueryModel"];
export type GetDataFetchModel = components["schemas"]["GetDataFetchModel"];
export type GetRequestTraceModel =
  components["schemas"]["GetRequestTraceModel"];
export type GetTraceStepModel = components["schemas"]["GetTraceStepModel"];
export type GetPromptVersionModel =
  components["schemas"]["GetPromptVersionModel"];
export type QueryExplorerItem = components["schemas"]["QueryExplorerItem"];
export type QueryExplorerRequestSummary =
  components["schemas"]["QueryExplorerRequestSummary"];

type AdminRequestsResponse = components["schemas"]["AdminRequestsResponse"];
type QueryExplorerResponse = components["schemas"]["QueryExplorerResponse"];

const UnauthorizedError = new Error("Unauthorized");

export const useAdminRequests = (
  limit: number = 50,
  offset: number = 0,
  status?: string,
  search?: string,
  hasFeedback?: boolean,
  isTest?: boolean,
  isFixed?: boolean,
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
    string | undefined,
    string | undefined,
    boolean | undefined,
    boolean | undefined,
    boolean | undefined,
  ]) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (status) {
      params.set("status", status);
    }
    if (search) {
      params.set("search", search);
    }
    if (hasFeedback) {
      params.set("has_feedback", "true");
    }
    if (isTest !== undefined) {
      params.set("is_test", String(isTest));
    }
    if (isFixed !== undefined) {
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

export const useRequestTrace = (requestId: string) => {
  const fetcher = (url: string) =>
    fetch(url).then((res) => {
      if (res.ok) return res.json();
      throw UnauthorizedError;
    });

  const { data, error, isLoading } = useSWR<GetRequestTraceModel>(
    requestId ? `/api/apegpt/admin/traces/${requestId}` : null,
    fetcher,
    {
      shouldRetryOnError: false,
      revalidateOnFocus: false,
    },
  );

  return {
    trace: data,
    error,
    isLoading,
  };
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

export const updateAdminRequest = async (
  requestId: string,
  patch: { is_test?: boolean; is_fixed?: boolean; fix_comment?: string },
): Promise<GetRequestModel> => {
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
  return res.json();
};

export const useQueryExplorer = (
  limit: number = 50,
  offset: number = 0,
  search?: string,
  hasFeedback: boolean = false,
) => {
  const fetcher = ([
    url,
    fetchLimit,
    fetchOffset,
    searchParam,
    feedbackFilter,
  ]: [string, number, number, string | undefined, boolean]) => {
    const params = new URLSearchParams({
      limit: String(fetchLimit),
      offset: String(fetchOffset),
    });
    if (searchParam) {
      params.set("search", searchParam);
    }
    if (feedbackFilter) {
      params.set("has_feedback", "true");
    }
    return fetch(`${url}?${params.toString()}`).then((res) => {
      if (res.ok) return res.json();
      throw UnauthorizedError;
    });
  };

  const { data, error, isLoading, mutate } = useSWR<QueryExplorerResponse>(
    ["/api/apegpt/admin/query-explorer", limit, offset, search, hasFeedback],
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
