"use client";

import {
  ArrowDownward,
  ArrowUpward,
  Edit,
  Insights,
  Link,
  SwapVert,
} from "@mui/icons-material";
import AddIcon from "@mui/icons-material/Add";
import { Box, IconButton, Tooltip } from "@mui/material";
import type { GridColDef } from "@mui/x-data-grid";
import type { GridSortItem } from "@mui/x-data-grid/models/gridSortModel";
import { useRouter } from "next/navigation";
import type { ReactElement, RefObject, SyntheticEvent } from "react";
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { createRequest } from "@/app/actions";
import { increaseTrialCount } from "@/app/chat/actions";
import { StyledValue } from "@/app/components/StyledValue";
import { AppContext } from "@/app/contexts/App";
import { isSolanaAddress, isSolanaSignature } from "@/app/helpers/cell";
import { pollForResponse } from "@/app/helpers/chat";
import { useInfiniteQuery } from "@/app/hooks/useInfiniteQuery";
import { useUserSession } from "@/app/hooks/useUserSession";
import type {
  TChatMessage,
  TChatSection,
  TColumn,
  TResponseResult,
} from "@/app/lib/types";

export const options: Record<
  string,
  { icon: ReactElement; label: string; cta: string }
> = {
  submit: {
    icon: <Edit fontSize="small" />,
    label: "Modify query with",
    cta: "Modify query with",
  },
  new: {
    icon: <Link fontSize="small" />,
    label: "New linked query for",
    cta: "Drill down on",
  },
  analyze: {
    icon: <Insights fontSize="small" />,
    label: "Analyze data of",
    cta: "Analyze data of",
  },
};

export interface ChatSessionContextType {
  rows: any[];
  gridColumns: GridColDef[];
  setNewCol: React.Dispatch<React.SetStateAction<boolean>>;
  sections: TChatSection[];
  setSections: React.Dispatch<React.SetStateAction<any[]>>;
  promptVal: string;
  setPromptVal: (p: string) => void;
  activeColumn: any | null;
  setActiveColumn: React.Dispatch<React.SetStateAction<GridColDef | null>>;
  activeRows: any[] | undefined | null;
  setActiveRows: React.Dispatch<React.SetStateAction<any[] | undefined>>;
  pending: boolean;
  setPending: (b: boolean) => void;
  placeholder: () => string;
  handleClick: (
    inputRef: RefObject<HTMLInputElement>,
    formRef: RefObject<HTMLFormElement>,
    id: string,
  ) => (e: any) => Promise<void>;
  handleKeyDown: (
    inputRef: RefObject<HTMLInputElement>,
    formRef: RefObject<HTMLFormElement>,
    id: string,
  ) => (e: React.KeyboardEvent) => Promise<void>;
  handleChange: (inputRef: RefObject<HTMLInputElement>) => (e: any) => void;
  onAdd: (message?: string) => { id: string; label: string; chat: string[] };
  onSelectColumn: (col: GridColDef | null) => void;
  onSelectRow: (rows: any[] | undefined) => void;
  lastMessages?: TChatMessage[];
  sects: TChatSection[];
  sortModel: GridSortItem[];
  setSortModel: React.Dispatch<React.SetStateAction<GridSortItem[]>>;
  paginationModel: { page: number; pageSize: number };
  setPaginationModel: React.Dispatch<{ page: number; pageSize: number }>;
  rowCount: number;
  isLoading: boolean;
  selectionModel: number[];
  setSelectionModel: React.Dispatch<React.SetStateAction<number[]>>;
  mergedSql: string | undefined;
  isReachingEnd: boolean;
  isValidating: boolean;
  setSize: React.Dispatch<React.SetStateAction<number>>;
  metadata: any;
  context: string;
  scrollRef: React.RefObject<HTMLDivElement>;
  scrollToBottom: () => void;
  abortController?: AbortController;
  selectedAction: keyof typeof options;
  setSelectedAction: React.Dispatch<React.SetStateAction<keyof typeof options>>;
  requestId: string | undefined;
  setRequestId: React.Dispatch<React.SetStateAction<string | undefined>>;
}

export const getDecision = async (
  prompt: string,
  messages: string[],
  validChoices: string[],
  sql?: string,
  rows?: any[] | null,
  cols?: any | null,
) => {
  const resp = await fetch("/api/ai/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      messages,
      validChoices,
      sql,
      rows,
      cols,
    }),
  });
  const data = await resp.json();
  console.log("decision", data?.decision?.decision);
  return data?.decision?.decision || "interactive_query";
};

const canonical = (metadata: any, field: string) =>
  metadata?.columns?.find(
    (c: any) => c.id === field || c.column_name === field,
  );

const enrichedContext = (selectedAction: string, context: string) => {
  if (context && context !== "General") {
    const contextParts = context.split(" ");
    const processedContextParts = contextParts.map((part) => {
      if (isSolanaAddress(part)) {
        return `${part.slice(0, 4)}...${part.slice(-4)}`;
      }
      if (isSolanaSignature(part)) {
        return `${part.slice(0, 8)}...${part.slice(-8)}`;
      }
      return part;
    });
    const processedContext = processedContextParts.join(" ");
    const actionLabel =
      (options[selectedAction || ""] || {})?.cta || selectedAction;
    return `${actionLabel} ${processedContext}`;
  }
  return "Describe how to change or refine this query..."; // selectedAction;
};

const extractSortModelFromSQL = (
  metadata: any,
  sql: string,
): GridSortItem[] => {
  const match = sql.match(/ORDER\s+BY\s+(.+?)(?:\s+LIMIT|\s+OFFSET|;?\s*$)/i);
  if (!match) return [];

  const clause = match[1];
  if (!clause) return [];

  // @ts-ignore
  return clause
    .split(",")
    .map((part) => part.trim())
    .map((part) => {
      const [field, direction] = part.split(/\s+/);
      if (!field) return undefined; // Skip if no field is specified

      return {
        field: canonical(metadata, field)?.column_name || "",
        sort: direction?.toLowerCase() === "desc" ? "desc" : "asc",
      };
    })
    .filter(Boolean);
};

const signatureSubstrings = ["signature", "hash", "tx", "transaction"];
const walletSubstrings = [
  "wallet",
  "address",
  "account",
  "mint",
  "owner",
  "trader",
  "seller",
  "from",
  "to",
];
const tickerSubstrings = ["symbol", "ticker"];

const columnWidth = (name: string) => {
  const isWallet = walletSubstrings.some((sub) => name.includes(sub));
  const isTicker = tickerSubstrings.some((sub) => name.includes(sub));
  const isSignature = signatureSubstrings.some((sub) => name.includes(sub));
  if (isSignature) {
    return 220; // Superwide for tx-related columns
  }
  if (isWallet) {
    return 480; // Wider for wallet-related columns
  }
  if (isTicker) {
    return 180; // Wider for ticker-related columns
  }
  return 200; // Default width for other columns
};

const withNewMessage =
  (request: TResponseResult, prompt: string) => (ss: TChatSection[]) => [
    ...ss,
    {
      id: "general",
      label: "General",
      chat: [prompt, ""],
      messages: [
        {
          uid: request?.request_id || "_req",
          isBot: false,
          text: prompt,
        },
        {
          uid: request?.request_id || "pending",
          isBot: true,
          text: "",
          status: "New",
        },
      ],
    },
  ];

const withPendingMessage =
  (status: TResponseResult, text: string) => (ss: TChatSection[]) =>
    ss.map((s, idx, allS) => ({
      ...s,
      status: idx < allS.length - 1 ? s.status : status.status,
      chat:
        // eslint-disable-next-line no-nested-ternary
        idx < allS.length - 1
          ? s.chat
          : s.chat
            ? [...s.chat.slice(0, s.chat.length - 1), text]
            : [text],
      messages:
        // eslint-disable-next-line no-nested-ternary
        idx < allS.length - 1
          ? s.messages
          : s.messages
            ? [
                ...s.messages.slice(0, s.messages.length - 1),
                {
                  uid: status.request_id || "pending",
                  text,
                  isBot: true,
                  status: status.status,
                },
              ]
            : [
                {
                  uid: status.request_id || "pending",
                  text,
                  isBot: true,
                  status: status.status,
                },
              ],
    }));

const withErrorResponse = (resp: TResponseResult) => (ss: TChatSection[]) =>
  ss.map((s: TChatSection, idx, allS) => ({
    ...s,
    status: idx < allS.length - 1 ? s.status : "Error",
    chat:
      // eslint-disable-next-line no-nested-ternary
      idx < allS.length - 1
        ? s.chat
        : s.chat
          ? [...s.chat.slice(0, s.chat.length - 1), ""]
          : [""],
    messages:
      // eslint-disable-next-line no-nested-ternary
      idx < allS.length - 1
        ? s.messages
        : s.messages
          ? [
              ...s.messages.slice(0, s.messages.length - 1),
              {
                uid: resp.request_id || "error",
                text: "Error",
                isBot: true,
                isError: true,
              },
            ]
          : [
              {
                uid: resp.request_id || "error",
                text: "Error",
                isBot: true,
                isError: true,
              },
            ],
  }));

export const Index = createContext<ChatSessionContextType | null>(null);

export const GridSessionProvider = ({
  sessionId,
  chat,
  metadata,
  ancestors,
  successors,
  pendingRequest,
  children,
}: {
  sessionId: string;
  chat: any;
  metadata: any;
  ancestors?: { name: string; id: string }[];
  successors?: { name: string; id: string }[];
  pendingRequest?: { session_id: string; sequence_number: number } | null;
  children: React.ReactNode;
}) => {
  const router = useRouter();
  const { model } = useContext(AppContext);
  const { mutate, data: userSession } = useUserSession(sessionId!);
  const [sections, setSections] = useState<TChatSection[]>([]);
  const [sects, setSects] = useState<TChatSection[]>([]);
  const [promptVal, setPromptVal] = useState("");
  const [prompt, setPrompt] = useState("");
  const [activeColumn, setActiveColumn] = useState<GridColDef | null>(null);
  const [activeRows, setActiveRows] = useState<any[]>();
  const [pending, setPending] = useState(false);
  const [lastMessages, setLastMessages] = useState<TChatMessage[]>([]);
  const [requestId, setRequestId] = useState<string>();

  const query = useMemo(() => {
    if (!requestId || !sections || sections.length === 0) {
      return null;
    }
    return sections.find((s) => s.requestId === requestId)?.query || null;
  }, [sections, requestId]);

  const [sortModel, setSortModel] = useState<GridSortItem[]>([]);
  const [paginationModel, setPaginationModel] = useState<{
    page: number;
    pageSize: number;
  }>({
    page: 0,
    pageSize: 100,
  });
  const [selectionModel, setSelectionModel] = useState<number[]>([]);
  const [newCol, setNewCol] = useState(false);
  const mergedSql = useMemo(
    () => query?.sql || userSession?.metadata?.sql || metadata?.sql,
    [metadata, userSession, query],
  );
  const [selectedAction, setSelectedAction] =
    useState<keyof typeof options>("submit");

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollToBottom = () => {
    if (!scrollRef.current) return;
    setTimeout(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }, 50); // allow DOM to update first
  };

  const onAdd = (message?: string) => {
    console.log("onAdd", message);
    setNewCol(true);
    if (!sections.some((s) => s.id === `new_column`)) {
      setSections((prevSections) => [
        ...prevSections,
        {
          id: `new_column`,
          label: message || `New Column`,
          chat: [],
          messages: [],
        },
      ]);
    }
    return {
      id: `new_column`,
      label: message || `New Column`,
      messages: [],
      chat: [],
    };
  };

  useEffect(() => {
    console.log("sections", sections);
    setSects(sections);
  }, [sections]);

  useEffect(() => {
    if (!sects.length) {
      setSects([
        {
          id: "new",
          label: "General",
          chat: [],
          messages: [],
        },
      ]);
    }
  }, []);

  useEffect(() => {
    if (chat) {
      // reduce chat.messages to sections by grouping pairs of messages via refs.columns
      // matching it with metadata.columns.
      // if refs is null, use 'general section'
      const pairs = [];
      for (let i = 0; i < chat.messages.length; i += 2) {
        pairs.push(chat.messages.slice(i, i + 2));
      }
      const sections = pairs.reduce(
        (acc: TChatSection[], pair: TChatMessage[], idx, chat) => {
          const userMessage = pair[0]; // Get the previous message (human)
          const apeResponse = pair[1]; // Get the previous message (human)
          const refCol = apeResponse?.structuredResponse?.refs?.cols?.[0];
          const refColMeta = metadata?.columns.find(
            (c: any) => c.id === refCol,
          );
          // console.log("refCol", refCol, refColMeta);
          if (refCol) {
            acc.push({
              id: apeResponse?.structuredResponse?.refs?.cols?.[0],
              requestId: apeResponse.uid,
              label: refColMeta
                ? refColMeta.column_alias
                : apeResponse?.structuredResponse?.refs?.cols?.[0],
              chat: [
                userMessage?.text || "",
                apeResponse?.text ||
                  apeResponse?.structuredResponse?.intro ||
                  "",
              ],
              messages: pair,
              linkedSession: apeResponse?.structuredResponse?.linked_session_id,
              query: apeResponse.query,
              view: apeResponse.view,
            });
          } else {
            // If no matching column, add to general section
            // const generalSection = acc.find((s: any) => s.id === "general");
            // console.log("generalSection", userMessage?.text, apeResponse);
            acc.push({
              id: "general",
              requestId: apeResponse?.uid,
              label: "General",
              status: apeResponse?.status,
              chat: [
                userMessage?.text || "",
                apeResponse?.text ||
                  apeResponse?.structuredResponse?.intro ||
                  "",
              ],
              messages: pair,
              linkedSession: apeResponse?.structuredResponse?.linked_session_id,
              query: apeResponse?.query,
              view: apeResponse?.view,
            });
          }
          return acc;
        },
        [],
      );
      setSections(sections);
    }
  }, [metadata, chat]);

  useEffect(() => {
    if (chat) {
      console.log("chat messages", chat.messages);
      // console.log("ancestors", ancestors);
      console.log("metadata", metadata);
      setLastMessages(chat.messages.slice(-2)); // Get last two messages
    }
  }, [chat, ancestors, metadata]);

  useEffect(() => {
    if (chat?.messages) {
      const pairs = [];
      for (let i = 0; i < chat.messages.length; i += 2) {
        pairs.push(chat.messages.slice(i, i + 2));
      }

      const newSections = pairs.map(([userMsg, botMsg]: TChatMessage[]) => {
        const refCol = botMsg?.structuredResponse?.refs?.cols?.[0];
        const label =
          metadata?.columns.find((c: any) => c.id === refCol)?.column_alias ||
          refCol ||
          "General";
        return {
          id: refCol || "general",
          requestId: botMsg?.uid,
          label,
          status: botMsg?.status,
          chat: [userMsg?.text, botMsg?.text || ""],
          messages: [userMsg, botMsg],
          linkedSession: botMsg?.structuredResponse?.linked_session_id,
          query: botMsg?.query,
          view: botMsg?.view,
        };
      });

      setSections(newSections as any[]);
    }
  }, [chat, metadata]);

  const sortByCol = metadata?.columns?.find(
    (c: any) =>
      c.id === sortModel[0]?.field || c.column_name === sortModel[0]?.field,
  );
  const sortBy = sortByCol?.column_name?.replace("col_", "");
  const sortOrder = sortModel[0]?.sort || "asc";

  const {
    rows: data,
    totalRows: dataRowCount,
    setSize,
    // isFetchingMore,
    isReachingEnd,
    error: dataError,
    isLoading,
    isValidating,
    abortController,
  } = useInfiniteQuery({
    id: requestId || sessionId,
    // todo: replace requestId with actual sql ??
    sql: query?.sql || metadata?.sql,
    sortBy,
    sortOrder,
  });
  const hasLoadedOnce = useRef(false);
  const triggered = useRef(false);

  useEffect(() => {
    if (activeRows && activeRows?.length < (data?.length || 0)) {
      setSelectedAction("new");
    } else if (activeRows) {
      setSelectedAction("analyze");
    } else {
      setSelectedAction("submit");
    }
  }, [activeRows, data?.length]);

  useEffect(() => {
    const ready = !isValidating && !isLoading && !isReachingEnd;

    if (ready && !triggered.current) {
      if (hasLoadedOnce.current) {
        triggered.current = true;
        console.log("revalidate session metadata");
        mutate(); // your metadata fetch
      } else {
        hasLoadedOnce.current = true;
      }
    }

    // Reset `triggered` if list is reloading again
    if (!ready) {
      triggered.current = false;
    }
  }, [isValidating, isLoading, isReachingEnd]);

  const onSortClick = (params: any) => (e: SyntheticEvent) => {
    e.preventDefault(); // prevent default behavior
    e.stopPropagation(); // prevent triggering other handlers
    const direction =
      sortModel[0]?.field === params.colDef.field &&
      sortModel[0]?.sort !== "asc"
        ? "asc"
        : "desc";

    console.log("set sortModel", params.colDef.field, direction);
    setSortModel([{ field: params.colDef.field, sort: direction }]);
  };

  const gridColumns: GridColDef[] = useMemo(() => {
    const columns = query?.columns || metadata?.columns;
    const userColumns =
      columns?.map((col: TColumn, idx: number) => ({
        field: col.column_name || `col_${idx}`,
        headerName: col.column_alias
          ?.replace(/_/g, " ")
          .replace(/^\w/, (c: any) => c.toUpperCase()),
        headerDescription: col.column_description,
        width: col.column_alias ? columnWidth(col.column_alias) : 200,
        sortable: false,
        headerClassName:
          activeColumn?.field === col.column_name
            ? "highlight-column-header"
            : "",
        renderCell: (params: any) => (
          <StyledValue
            columnType={col.column_type?.replace("Nullable(", "")}
            value={params.value}
            params={params}
            successors={successors}
          />
        ),
        renderHeader: (params: any) => (
          <Tooltip
            title={params.colDef.headerDescription || params.colDef.headerName}
          >
            <Box display="flex" alignItems="center">
              <span>{params.colDef.headerName}</span>
              <IconButton size="small" onClick={onSortClick(params)}>
                {sortModel[0] &&
                  col.column_name === sortModel[0].field &&
                  sortModel[0]?.sort === "asc" && <ArrowDownward />}
                {sortModel[0] &&
                  col.column_name === sortModel[0].field &&
                  sortModel[0]?.sort === "desc" && <ArrowUpward />}
                {(!sortModel[0] || col.column_name !== sortModel[0]?.field) && (
                  <SwapVert color="disabled" />
                )}
              </IconButton>
            </Box>
          </Tooltip>
        ),
      })) || [];

    const addColumn: GridColDef = {
      field: "__add_column__",
      headerName: "",
      sortable: false,
      filterable: false,
      width: 70,
      disableColumnMenu: true,
      renderHeader: () => (
        <Box
          display="flex"
          justifyContent="center"
          alignItems="center"
          height="100%"
        >
          <Tooltip title="Add new column">
            <IconButton
              size="small"
              color="primary"
              onClick={() => {
                const newColumn = onAdd("New column"); // make sure onAdd is in scope
                setActiveColumn({
                  field: newColumn?.id || "new_column",
                  headerName: newColumn?.label || "New Column",
                });
              }}
              sx={{ border: "solid 1px #EF8626" }}
            >
              <AddIcon sx={{ fontSize: "12px" }} />
            </IconButton>
          </Tooltip>
        </Box>
      ),
    };

    return [...userColumns, addColumn];
  }, [sections, activeColumn, metadata, sortModel, successors, query]);

  const rows = useMemo(
    () =>
      (data || []).map((row: Record<string, any>, idx: number) => ({
        id: idx, // Use index as ID
        ...Object.values(row)
          .slice(0)
          .reduce((acc, val, idx) => {
            const col = gridColumns[idx];
            if (col) {
              acc[col.field] = val || ""; // Map cell to column field
            }
            return acc;
          }, {}),
      })),
    [data, gridColumns],
  );

  const rowCountRef = React.useRef(dataRowCount || metadata?.row_count || 0);

  const rowCount = React.useMemo(() => {
    if (dataRowCount !== undefined) {
      rowCountRef.current = dataRowCount;
    }
    if (metadata?.row_count !== undefined) {
      rowCountRef.current = metadata.row_count;
    }
    return rowCountRef.current;
  }, [dataRowCount]);

  const refs = useMemo(
    () => ({
      cols:
        activeColumn &&
        activeColumn.field !== "__add_column__" &&
        activeColumn.field !== "general"
          ? [
              canonical(metadata, activeColumn.field)?.column_name,
              ...data.map((r) =>
                r[
                  canonical(metadata, activeColumn.field)?.column_name
                ]?.toString(),
              ),
            ]
          : undefined,
      rows: activeRows
        ? [
            metadata.columns.map((c: any) => c.column_alias || c.id),
            ...activeRows
              .filter(Boolean)
              .map((r: any) => Object.values(r).slice(1).filter(Boolean)),
          ]
        : undefined,
    }),
    [activeColumn, activeRows, data, metadata],
  );

  const context = useMemo(() => {
    // console.log("ctx", activeRows);
    if (activeColumn?.field === "__add_column__")
      return `${activeColumn?.headerName}` || "New column";
    if (activeColumn && activeColumn.headerName !== "General")
      return `column: ${activeColumn?.headerName}` || "";
    if (activeRows) {
      if (activeRows.length > 1) return `${activeRows.length} rows`;
      if (activeRows.length === 1 && activeRows[0]?.wallet)
        return (
          `wallet ${activeRows[0]?.wallet}` ||
          `${gridColumns?.[0]?.headerName} ${Object.values(activeRows[0])[1]}`
        );
      if (Object.values(activeRows)[0])
        return `${gridColumns?.[0]?.headerName} ${Object.values(activeRows[0] || {})[1] || "-"}`;
      return "row";
    }
    return "General";
  }, [activeRows, activeColumn, gridColumns]);

  useEffect(() => {
    // console.log("context", context);
  }, [context]);

  const requestType = () => {
    switch (selectedAction) {
      case "submit":
        return "interactive_query";
      case "new":
        return "linked_session";
      case "analyze":
        return "data_analysis";
      default:
        return "tbd";
    }
  };

  // WAIT EFFECT == RESPONSE POLLING FOR PENDING REQUEST
  useEffect(() => {
    if (pendingRequest) {
      console.log("pendingRequest", pendingRequest);
      // newPendingMessage(prompt)]);
      setPending(true);
      scrollToBottom();
      // wait for response by polling
      const { onStatus, waitForDone } = pollForResponse({
        sessionId: pendingRequest.session_id,
        seqNum: pendingRequest.sequence_number,
      });
      onStatus((status: TResponseResult) => {
        if (status.status === "Intent") {
          mutate();
        }
        const text = status.response || status.intent || "";
        setSects(withPendingMessage(status, text));
      });
      waitForDone
        .then(async (resp: TChatMessage) => {
          // GOT THE RESPONSE
          if (resp.structuredResponse?.linked_session_id) {
            // create new linked session
            console.log(
              "linked session created",
              resp.structuredResponse.linked_session_id,
            );
            requestAnimationFrame(() => {
              console.log("redirecting to new session");
              router.push(
                `/query/${resp.structuredResponse?.linked_session_id}`,
              );
            });
          } else {
            setSects(
              withPendingMessage(
                resp as unknown as TResponseResult,
                resp.text || "",
              ),
            );
          }
        })
        .then((_) => increaseTrialCount())
        .then(() => setPrompt(""))
        .then(() => setPending(false))
        .then(() => scrollToBottom())
        .catch((e) => {
          console.error("error response", e);
          setPending(false);
          setSects(withErrorResponse({ err: e } as TResponseResult));
        });
    }
  }, [pendingRequest]);

  useEffect(() => {
    setPrompt("");
  }, [activeColumn]);

  // MAIN EFFECT == HANDLE USER QUERY SUBMISSION AND RESPONSE POLLING
  useEffect(() => {
    if (prompt) {
      setPending(true);
      createRequest({
        request: prompt,
        requestType: requestType(),
        flow: "Interactive",
        model: model.value,
        db: "V2",
        sessionId,
        refs,
        queryId: query?.query_id,
      })
        .then((request) => {
          console.log("request", request);
          setSects(withNewMessage(request as any, prompt));
          return request;
        })
        .then((req) => {
          if (scrollRef.current) {
            scrollToBottom();
          }
          return req;
        })
        // wait for response by polling
        // @ts-ignore
        .then(async ({ session_id, sequence_number }) => {
          const { onStatus, waitForDone } = pollForResponse({
            sessionId: session_id,
            seqNum: sequence_number,
          });
          console.log("pollForResponse", session_id, sequence_number);
          await mutate();
          onStatus((status) => {
            if (status.status === "Intent") {
              mutate();
            }
            const text = status.response || status.intent || "";
            setSects(withPendingMessage(status, text));
          });
          waitForDone
            .then(async (resp: TChatMessage) => {
              // GOT THE RESPONSE
              if (resp.structuredResponse?.linked_session_id) {
                // create new linked session
                console.log(
                  "linked session created",
                  resp.structuredResponse.linked_session_id,
                );
                await mutate(); // refresh sessions
                requestAnimationFrame(() => {
                  console.log("redirecting to new session");
                  router.push(
                    `/query/${resp.structuredResponse?.linked_session_id}`,
                  );
                });
              } else {
                setSects(
                  withPendingMessage(
                    resp as unknown as TResponseResult,
                    resp.text || "",
                  ),
                );
              }
            })
            .then((_) => increaseTrialCount())
            .then(() => setPrompt(""))
            .then(() => setPending(false))
            .then(() => scrollToBottom())
            .catch((e) => {
              console.error("error response", e);
              setPending(false);
              setSects(withErrorResponse({ err: e } as TResponseResult));
            });
        })
        .catch((e) => {
          console.error("error response", e);
          setPending(false);
          setSects(withErrorResponse({ err: e } as TResponseResult));
        });
    }
  }, [prompt]);

  useEffect(() => {
    if (mergedSql) {
      const model = extractSortModelFromSQL(metadata, mergedSql);
      // console.log("extracted sort model", model);
      setSortModel(model.slice(0, 1)); // Use only the first sort item
    }
  }, [mergedSql]);

  const placeholder = () => {
    if (activeColumn?.field === "__add_column__") return `Ask to add...`;

    if (activeColumn || activeRows)
      return `${enrichedContext(selectedAction, context)}...`;

    return "Describe how to change or refine this query...";
  };

  const handleClick =
    (
      inputRef: RefObject<HTMLInputElement>,
      formRef: RefObject<HTMLFormElement>,
      id: string,
    ) =>
    async (e: any) => {
      e.preventDefault();
      setPrompt(promptVal || "");
      setPromptVal("");
    };

  const handleKeyDown =
    (
      inputRef: RefObject<HTMLInputElement>,
      formRef: RefObject<HTMLFormElement>,
      id: string,
    ) =>
    async (e: React.KeyboardEvent) => {
      // console.log("handleKeyDown", inputRef.current, formRef.current, e);
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault(); // Block default behavior immediately
        e.stopPropagation();
        console.log(
          "submit request",
          selectedAction,
          promptVal,
          activeRows,
          activeColumn,
        );
        setPrompt(promptVal || "");
        // check is promptVal is one of the suggested tutorial options
        setPromptVal("");
      }
    };

  // TODO: remove if not used
  const handleChange = (inputRef: RefObject<HTMLInputElement>) => (e: any) => {
    // console.log("handleChange", e.target.value, inputRef.current);
    if (inputRef.current) {
      // Update value without triggering re-render
      inputRef.current.value = e.target.value;
      // setVal(e.target.value);
    }
  };

  const onSelectRow = (row: any) => {
    setActiveRows(
      // eslint-disable-next-line no-nested-ternary
      row ? (activeRows ? [...activeRows, row] : [row]) : undefined,
    );
    setActiveColumn(null); // Clear active column on row selection
    setNewCol(false); // Clear new column state
    if (!row) {
      setSelectionModel([]);
    }
    setSelectionModel((rr) => (row ? [...rr, row.id] : [...rr])); // Set selection model to the selected row
  };

  const onSelectColumn = (col: any) => {
    setActiveColumn(col);
    setNewCol(false);
  };

  return (
    <Index.Provider
      value={{
        rows,
        gridColumns,
        sections,
        setSections,
        activeColumn,
        setActiveColumn,
        activeRows,
        setActiveRows,
        pending,
        setPending,
        promptVal,
        setPromptVal,
        placeholder,
        handleClick,
        handleKeyDown,
        handleChange,
        onSelectRow,
        onSelectColumn,
        sects,
        lastMessages,
        onAdd,
        sortModel,
        setSortModel,
        paginationModel,
        setPaginationModel,
        rowCount,
        isLoading,
        selectionModel,
        setSelectionModel,
        setNewCol,
        mergedSql,
        isReachingEnd,
        isValidating,
        setSize,
        metadata,
        context,
        scrollRef,
        scrollToBottom,
        abortController,
        selectedAction,
        setSelectedAction,
        requestId,
        setRequestId,
      }}
    >
      {children}
    </Index.Provider>
  );
};

export const useGridSession = (): ChatSessionContextType => {
  const ctx = useContext(Index);
  if (!ctx)
    throw new Error("useGridSession must be used within a GridSessionProvider");
  return ctx;
};
