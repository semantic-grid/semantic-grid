"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

type ViewKey = "chart" | "grid" | "sql";
const VIEW_KEYS: ViewKey[] = ["chart", "grid", "sql"];

type ChartType = "pie" | "line" | "bar";
const CHART_TYPES: ChartType[] = ["pie", "line", "bar"];

type Ctx = {
  view: ViewKey;
  setView: (next: ViewKey) => void;
  chartType: ChartType;
  setChartType: (next: ChartType) => void;
  itemId: string;
  // Available chart types based on data shape (set by parent component)
  availableChartTypes: ChartType[];
  setAvailableChartTypes: (types: ChartType[]) => void;
};

function useBaseUrl() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  return useMemo(() => {
    const qs = searchParams?.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  }, [pathname, searchParams]);
}

function readHash(): ViewKey | null {
  if (typeof window === "undefined") return null;
  const h = window.location.hash.replace(/^#/, "");
  return VIEW_KEYS.includes(h as ViewKey) ? (h as ViewKey) : null;
}

export const Index = createContext<Ctx | null>(null);

export const ItemViewProvider = ({
  itemId,
  defaultView = "chart",
  defaultChartType = "line",
  children,
}: {
  itemId: string;
  defaultView?: ViewKey;
  defaultChartType?: ChartType;
  children: React.ReactNode;
}) => {
  const router = useRouter();
  const baseUrl = useBaseUrl();

  const readLocal = (): ViewKey | null => {
    if (typeof window === "undefined") return null;
    const v = window.localStorage.getItem(`itemView:${itemId}`);
    return VIEW_KEYS.includes(v as ViewKey) ? (v as ViewKey) : null;
  };

  const readChartTypeLocal = (): ChartType | null => {
    if (typeof window === "undefined") return null;
    const ct = window.localStorage.getItem(`chartType:${itemId}`);
    return CHART_TYPES.includes(ct as ChartType) ? (ct as ChartType) : null;
  };

  const hash = readHash();

  // Resolve initial state (hash > localStorage > default)
  const initial = (readHash() ?? readLocal() ?? defaultView) as ViewKey;
  const [view, setViewState] = useState<ViewKey>(initial);

  // Chart type state (localStorage > default)
  const initialChartType = (readChartTypeLocal() ??
    defaultChartType) as ChartType;
  const [chartType, setChartTypeState] = useState<ChartType>(initialChartType);

  // Available chart types (defaults to all, can be filtered by parent based on data)
  const [availableChartTypes, setAvailableChartTypes] =
    useState<ChartType[]>(CHART_TYPES);

  // Ensure URL reflects the resolved initial view on mount
  useEffect(() => {
    if (!readHash()) {
      router.replace(`${baseUrl}#${view}`, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep state in sync with manual hash edits + back/forward
  useEffect(() => {
    const onHash = () => {
      const h = readHash();
      if (h && h !== view) setViewState(h);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [view]);

  // Cross-tab sync: if another tab changes localStorage, update here (and URL)
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === `itemView:${itemId}` && e.newValue) {
        const nv = e.newValue as ViewKey;
        if (VIEW_KEYS.includes(nv) && nv !== view) {
          setViewState(nv);
          router.replace(`${baseUrl}#${nv}`, { scroll: false });
        }
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [itemId, baseUrl, router, view]);

  const setView = (next: ViewKey) => {
    if (!VIEW_KEYS.includes(next)) return;
    setViewState(next);
    // Update URL fragment (no RSC refetch), also persist per item
    router.replace(`${baseUrl}#${next}`, { scroll: false });
    if (typeof window !== "undefined") {
      window.localStorage.setItem(`itemView:${itemId}`, next);
    }
  };

  const setChartType = (next: ChartType) => {
    if (!CHART_TYPES.includes(next)) return;
    setChartTypeState(next);
    // Persist chart type per item
    if (typeof window !== "undefined") {
      window.localStorage.setItem(`chartType:${itemId}`, next);
    }
  };

  const value = useMemo(
    () => ({
      view,
      setView,
      chartType,
      setChartType,
      itemId,
      availableChartTypes,
      setAvailableChartTypes,
    }),
    [view, chartType, itemId, availableChartTypes],
  );

  return <Index.Provider value={value}>{children}</Index.Provider>;
};

// Consumer hook
export function useItemViewContext() {
  const ctx = useContext(Index);
  if (!ctx)
    throw new Error("useItemViewContext must be used within a Provider");
  return ctx;
}
