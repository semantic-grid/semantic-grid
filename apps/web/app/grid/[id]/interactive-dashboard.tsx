"use client";

import {
  alpha,
  Box,
  CircularProgress,
  Container,
  Slide,
  Stack,
  Tab,
  Tabs,
} from "@mui/material";
import { BarChart, LineChart, PieChart } from "@mui/x-charts";
import type { GridColDef } from "@mui/x-data-grid";
import { useRouter } from "next/navigation";
import React, { useContext, useEffect, useMemo, useRef, useState } from "react";

import { QueryDataGrid } from "@/app/components/QueryDataGrid";
import type { DataGridRefs } from "@/app/components/QueryDataGrid/types";
import HighlightedSQL from "@/app/components/SqlView";
import { AppContext } from "@/app/contexts/App";
import { useGridSession } from "@/app/contexts/GridSession";
import { useItemViewContext } from "@/app/contexts/ItemView";
import { useSessionContext } from "@/app/contexts/SessionStatus";
import { ThemeContext } from "@/app/contexts/Theme";
import {
  buildGridColumns,
  buildPieChartSeries,
  normalizeDataSet,
  timeKey,
} from "@/app/helpers/chart";
import { useAppUser } from "@/app/hooks/useAppUser";
import { useLocalStorage } from "@/app/hooks/useLocalStorage";
import type { TColumn } from "@/app/lib/types";

import { ChatContainer } from "./chat-container";

export interface IInteractiveDashboardProps {
  // user?: Claims | null;
  metadata?: {
    columns: TColumn[]; // Metadata columns
    id: string;
    parents?: string[];
    result?: string;
    sql?: string;
    summary?: string;
    row_count?: number;
    explanation?: any;
  };
  id?: string;
  // error?: any;
  // pendingRequest?: { session_id: string; sequence_number: number } | null; // Pending message, if any
  ancestors?: { id: string; name: string }[]; // Ancestors of the current chat
  successors?: { name: string; id: string; refs?: any; session_id?: string }[]; // Children/linked sessions
  welcomeMessage?: string | null;
  suggestedPrompts?: string[];
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const CustomTabPanel = (props: TabPanelProps) => {
  const { children, value, index, ...other } = props;

  return (
    <Box
      role="tabpanel"
      hidden={value !== index}
      id={`simple-tabpanel-${index}`}
      aria-labelledby={`simple-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ pb: 0 }}>{children}</Box>}
    </Box>
  );
};

export const InteractiveDashboard = ({
  id,
  metadata,
  // pendingRequest,
  ancestors = [],
  successors = [],
  welcomeMessage,
  suggestedPrompts,
}: IInteractiveDashboardProps) => {
  const {
    rows,
    sections,
    pending,
    isLoading,
    mergedSql,
    isReachingEnd,
    isValidating,
    loadMoreRows,
    scrollToBottom,
    requestId,
    activeColumn,
    setActiveColumn,
    activeRows,
    setActiveRows,
    selectionModel,
    setSelectionModel,
    setNewCol,
    onFetchData,
    query: sessionQuery,
  } = useGridSession();
  const { user: appUser } = useAppUser();
  const { mode, isLarge } = useContext(ThemeContext);
  const { tab, setTab } = useContext(AppContext);
  const [panel, setPanel] = useState(0);
  const [leftWidth, setLeftWidth] = useLocalStorage<string>(
    `apegpt-left-width-${id}`,
    "",
  );
  const [maxLeftWidth, setMaxLeftWidth] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isDragging = useRef(false);
  const prevY = useRef<number | null>(null);
  const prevX = useRef<number | null>(null);
  const maxLeftWidthRef = useRef<number | null>(null);

  const [, setAnchorEl] = useState<null | HTMLElement>(null);
  const router = useRouter();
  const { latestUpdate } = useSessionContext();
  const pendingRequest = useMemo(
    () =>
      latestUpdate?.status !== "Done" &&
      !latestUpdate?.has_error &&
      latestUpdate?.status !== "Cancelled",
    [latestUpdate],
  );

  // Use query from GridSessionProvider (already computed based on requestId)
  const query = sessionQuery;

  // Performance warning info from query
  const performanceWarning = query?.explanation?.performance_warning ?? false;
  const estimatedRows = query?.explanation?.estimated_rows;
  const estimatedSizeGb = query?.explanation?.estimated_size_gb;

  // Handler for add column
  const handleAddColumn = () => {
    setNewCol(true);
    setActiveColumn({
      field: "new_column",
      headerName: "New Column",
    } as GridColDef);
  };

  const gridRef = useRef<HTMLDivElement | null>(null);

  const handleOpenMenu = (e: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(e.currentTarget);
  };
  const handleCloseMenu = (e: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(null);
  };

  const hasParent = useMemo(
    () => ancestors?.filter((a) => a.id !== id).length > 0,
    [ancestors, id],
  );

  const hasData = useMemo(
    () =>
      (Boolean(metadata?.id) &&
        // Boolean(metadata?.row_count) &&
        Boolean(metadata?.sql)) ||
      hasParent,
    [metadata, hasParent],
  );

  const showGrid = useMemo(
    () =>
      hasData ||
      Boolean((pendingRequest as any)?.sql) ||
      Boolean((pendingRequest as any)?.query?.sql),
    [hasData, pendingRequest],
  );
  // console.log("showGrid", showGrid, "hasData", hasData);

  useEffect(() => {
    // setLeftWidth(window.innerWidth);
    // console.log("leftWidth", leftWidth);
  }, [leftWidth]);

  useEffect(() => {
    scrollToBottom();
  }, []);

  useEffect(() => {
    // console.log("hasData", hasData, "leftWidth", leftWidth);
    if (!showGrid) {
      setLeftWidth(""); // Reset left width if no data
    } else if (showGrid && !leftWidth) {
      setLeftWidth((window.innerWidth / 3).toString()); // Default to 1/3 of the window width
    }
  }, [showGrid, leftWidth]);
  // console.log("leftWidth", metadata?.id, leftWidth);

  useEffect(() => {
    maxLeftWidthRef.current = maxLeftWidth;
  }, [maxLeftWidth]);

  useEffect(() => {
    if (contentRef.current) {
      // const { scrollWidth } = contentRef.current;
      const scrollWidth = window.innerWidth - 300; // Adjust as needed
      setMaxLeftWidth(scrollWidth); // buffer if needed
    }
  }, [sections, contentRef]);

  const handleMouseDown = (e: MouseEvent) => {
    isDragging.current = true;
    document.body.style.userSelect = "none";
    prevX.current = e.clientX;
    document.body.style.cursor = "col-resize";
  };

  const handleMouseMove = (e: MouseEvent) => {
    const maxWidth = maxLeftWidthRef.current;
    if (!isDragging.current || !containerRef.current || !maxWidth) return;

    const containerRect = containerRef.current.getBoundingClientRect();
    const offsetX = e.clientX - containerRect.left;

    const direction =
      prevX.current !== null && e.clientX > prevX.current ? "right" : "left";
    prevX.current = e.clientX;

    const clamped = Math.max(300, offsetX);

    // Prevent stretching beyond content
    if (
      direction === "right" &&
      parseInt(leftWidth) >= maxWidth &&
      offsetX >= parseInt(leftWidth)
    ) {
      return;
    }

    if (hasData) {
      setLeftWidth(Math.min(clamped, maxWidth).toString());
    } else {
      setLeftWidth(clamped.toString());
    }
  };

  const handleMouseUp = () => {
    isDragging.current = false;
    prevY.current = null;
    document.body.style.cursor = "default";
    document.body.style.userSelect = "auto";
  };

  useEffect(() => {
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  useEffect(() => {
    const handleInfiniteScroll = (event: React.UIEvent<HTMLDivElement>) => {
      const grid = gridRef.current;
      if (!grid) return;
      const scrollable = grid.querySelector(
        ".MuiDataGrid-virtualScroller",
      ) as HTMLDivElement;
      if (
        scrollable &&
        scrollable.scrollTop + scrollable.clientHeight >=
          scrollable.scrollHeight - window.innerHeight * 1.5
      ) {
        if (!isReachingEnd && !isLoading && !isValidating) {
          console.log("Nearing the bottom, loading more data...");
          loadMoreRows();
        }
      }
    };

    if (!rows || isLoading) {
      return; // No data to attach scroll listener
    }

    const grid = gridRef.current;
    const scrollable = grid?.querySelector(".MuiDataGrid-virtualScroller");
    scrollable?.addEventListener("scroll", handleInfiniteScroll as any);
    // eslint-disable-next-line consistent-return
    return () =>
      scrollable?.removeEventListener("scroll", handleInfiniteScroll as any);
  }, [gridRef, rows, isLoading]);

  const [contextMenu, setContextMenu] = React.useState<{
    mouseX: number;
    mouseY: number;
  } | null>(null);

  const handleContextMenu = (event: React.MouseEvent) => {
    event.preventDefault();

    setContextMenu(
      contextMenu === null
        ? {
            mouseX: event.clientX + 2,
            mouseY: event.clientY - 6,
          }
        : // repeated contextmenu when it is already open closes it with Chrome 84 on Ubuntu
          // Other native context menus might behave different.
          // With this behavior we prevent contextmenu from the backdrop to re-locale existing context menus.
          null,
    );

    // Prevent text selection lost after opening the context menu on Safari and Firefox
    const selection = document.getSelection();
    if (selection && selection.rangeCount > 0) {
      const range = selection.getRangeAt(0);

      setTimeout(() => {
        selection.addRange(range);
      });
    }
  };

  const handleClose = () => {
    setContextMenu(null);
  };

  useEffect(() => {
    if (pending) {
      setContextMenu(null);
    }
  }, [pending]);

  const onPanelChange = (event: React.SyntheticEvent, newValue: number) => {
    setPanel(newValue);
  };

  // Use data from GridSession instead of making a separate fetch
  // Charts only need first 20 rows
  const data = useMemo(() => {
    if (!rows || rows.length === 0) return null;
    return {
      rows: rows.slice(0, 20),
      total_rows: rows.length,
    };
  }, [rows]);

  const gridColumns: GridColDef[] = useMemo(() => {
    if (!query) return [];

    const userColumns = buildGridColumns(query, { successors });

    return [...userColumns];
  }, [query, successors]);

  const guessedChartType = useMemo(() => {
    // guess based on gridColumns, i.e. if type of the first column is date, then line chart
    if (timeKey(gridColumns[0]?.type)) return "line";
    return "pie"; // default
  }, [gridColumns]);

  const { view, setChartType, chartType } = useItemViewContext();

  useEffect(() => {
    // if (guessedChartType) {
    setChartType(guessedChartType);
    // }
  }, []);

  const pieSeries = useMemo(
    () => buildPieChartSeries(data?.rows || [], gridColumns),
    [data?.rows, gridColumns],
  );

  const lineChartSeries = useMemo(
    () =>
      gridColumns.slice(1).map((col) => ({
        id: col.field?.replace("col_", ""),
        label: col.headerName,
        dataKey: col.field?.replace("col_", ""), // EXACTLY matches dataset key
        showMark: false,
      })),
    [gridColumns],
  );

  const xAxis = useMemo(
    () => [
      {
        dataKey: gridColumns[0]?.field?.replace("col_", ""),
        scaleType: chartType === "bar" ? "band" : "time",
        // valueFormatter: (value: Date) => value.toLocaleDateString(),
        valueFormatter: (value: number) => new Date(value).toLocaleDateString(),
      },
    ],
    [gridColumns, chartType],
  );

  const dataset = useMemo(
    () => normalizeDataSet(data?.rows || [], gridColumns),
    [data?.rows, gridColumns],
  );

  // we need to determine if the new query is an ancestor or a successor and set the slide direction accordingly

  return isLarge ? (
    <Box
      ref={containerRef}
      sx={{
        height: showGrid ? "calc(100vh - 64px)" : "auto", // let height expand naturally
        // marginTop: "50px", // padding to avoid overlap with app bar
        display: "flex",
        flexDirection: "row", // default direction
        width: "100%",
        position: "relative",
        justifyContent: "center",
        overflowX: "hidden",
        overflowY: showGrid ? "auto" : "visible", // disable internal scroll
        // border: "1px solid #EF8626",
      }}
    >
      {/* Left pane - chat */}
      <Box
        sx={{
          width: showGrid ? `${leftWidth}px` : "100%", // full width when standalone
          maxWidth: showGrid && maxLeftWidth ? `${maxLeftWidth}px` : "100%",
          flexGrow: showGrid ? 1 : 0,
          flexBasis: showGrid ? leftWidth : "auto",
          overflow: "visible", // prevent clipping/scrolling
          display: "flex",
          flexDirection: "column",
          position: "relative",
        }}
      >
        <Container
          ref={contentRef}
          maxWidth="md"
          sx={{ position: "relative", "& .MuiContainer-root": { px: 0 } }}
        >
          <ChatContainer
            id={id || ""}
            hasParent={ancestors.length > 0}
            pendingRequest={pendingRequest}
            hasData={showGrid}
            metadata={metadata}
            welcomeMessage={welcomeMessage}
            suggestedPrompts={suggestedPrompts}
          />
        </Container>
      </Box>

      {/* Divider handle */}
      {showGrid && (
        <Box
          component="div"
          // @ts-ignore
          onMouseDown={handleMouseDown}
          sx={{
            width: "3px",
            cursor: "col-resize",
            backgroundColor: mode === "light" ? "grey.200" : "grey.900",
            "&:hover": { backgroundColor: "grey.600" },
          }}
        />
      )}

      {/* Right panel -- table */}
      {showGrid && (
        <Box
          sx={{
            // marginTop: "80px", // padding to avoid overlap with app bar
            overflow: "hidden",
            width: `calc(100vw - ${leftWidth}px - 3px)`,
          }}
        >
          <Container
            sx={{ position: "relative", width: "100%", marginTop: 0 }}
            maxWidth={false}
          >
            <Slide
              direction="left"
              in={showGrid}
              mountOnEnter
              unmountOnExit
              timeout={400} // customize speed
            >
              <Box>
                <CustomTabPanel value={tab} index={0}>
                  <Box
                    sx={{
                      height: "calc(100vh - 64px)",
                      position: "relative",
                      overflow: "auto",
                    }}
                    ref={gridRef}
                  >
                    {view === "chart" && chartType === "line" && (
                      <>
                        <LineChart
                          yAxis={[{ width: 100 }]}
                          style={{ height: "80vh", width: "100%" }}
                          xAxis={xAxis as any} // e.g. 'col_0'
                          series={lineChartSeries}
                          dataset={dataset}
                        >
                          {/* enables tooltips for all series at hovered X */}
                        </LineChart>
                        {isLoading && (
                          <Box
                            position="absolute"
                            top={0}
                            left={0}
                            right={0}
                            bottom={0}
                            display="flex"
                            justifyContent="center"
                            alignItems="center"
                            bgcolor={(theme) =>
                              alpha(theme.palette.background.default, 0.6)
                            }
                          >
                            <CircularProgress />
                          </Box>
                        )}
                      </>
                    )}
                    {view === "chart" && chartType === "bar" && (
                      <>
                        <BarChart
                          yAxis={[{ width: 100 }]}
                          style={{ height: "80vh", width: "100%" }}
                          xAxis={xAxis as any} // e.g. 'col_0'
                          series={lineChartSeries}
                          dataset={dataset}
                        >
                          {/* enables tooltips for all series at hovered X */}
                        </BarChart>
                        {isLoading && (
                          <Box
                            position="absolute"
                            top={0}
                            left={0}
                            right={0}
                            bottom={0}
                            display="flex"
                            justifyContent="center"
                            alignItems="center"
                            bgcolor={(theme) =>
                              alpha(theme.palette.background.default, 0.6)
                            }
                          >
                            <CircularProgress />
                          </Box>
                        )}
                      </>
                    )}
                    {view === "chart" && chartType === "pie" && (
                      <>
                        <PieChart series={pieSeries} width={200} height={200} />
                        {isLoading && (
                          <Box
                            position="absolute"
                            top={0}
                            left={0}
                            right={0}
                            bottom={0}
                            display="flex"
                            justifyContent="center"
                            alignItems="center"
                            bgcolor={(theme) =>
                              alpha(theme.palette.background.default, 0.6)
                            }
                          >
                            <CircularProgress />
                          </Box>
                        )}
                      </>
                    )}
                    {view === "sql" && (
                      <Box
                        sx={{
                          "& p": {
                            fontFamily: "monospace",
                            whiteSpace: "pre-wrap",
                            color: "text.secondary",
                          },
                        }}
                      >
                        <HighlightedSQL
                          code={
                            query?.sql || "No SQL available for this query."
                          }
                        />
                      </Box>
                    )}
                    {view === "grid" && query?.query_id && (
                      <QueryDataGrid
                        queryId={query.query_id}
                        columns={gridColumns}
                        queryMetadata={query}
                        paginate={true}
                        pageSize={100}
                        performanceWarning={performanceWarning}
                        estimatedRows={estimatedRows}
                        estimatedSizeGb={estimatedSizeGb}
                        activeColumn={activeColumn}
                        onActiveColumnChange={setActiveColumn}
                        activeRows={activeRows ?? undefined}
                        onActiveRowsChange={setActiveRows}
                        selectionModel={selectionModel}
                        onSelectionModelChange={setSelectionModel}
                        showAddColumn={true}
                        onAddColumn={handleAddColumn}
                        userEmail={appUser?.email}
                      />
                    )}
                    {/* <Popover
                      open={!!contextMenu}
                      onClose={handleClose}
                      anchorReference="anchorPosition"
                      anchorPosition={
                        contextMenu !== null
                          ? {
                              top: contextMenu.mouseY,
                              left: contextMenu.mouseX,
                            }
                          : undefined
                      }
                    >
                      <Paper sx={{ width: 600, px: 3, pb: 3 }}>
                        <QueryBox
                          id={id!}
                          formRef={formRef}
                          inputRef={inputRef}
                          handleClick={handleClick(inputRef, formRef, id!)}
                          handleKeyDown={handleKeyDown(inputRef, formRef, id!)}
                          handleChange={handleChange(inputRef)}
                        />
                      </Paper>
                    </Popover> */}
                  </Box>
                </CustomTabPanel>
                <CustomTabPanel value={tab} index={1}>
                  <Box
                    sx={{
                      overflowY: "auto",
                      maxHeight: "calc(100vh - 50px)",
                    }}
                  >
                    <Box
                      sx={{
                        "& p": {
                          fontFamily: "monospace",
                          whiteSpace: "pre-wrap",
                          color: "text.secondary",
                        },
                      }}
                    >
                      <HighlightedSQL
                        code={mergedSql || "No SQL available for this query."}
                      />
                    </Box>
                  </Box>
                </CustomTabPanel>
              </Box>
            </Slide>
          </Container>
        </Box>
      )}
    </Box>
  ) : (
    <Box
      ref={containerRef}
      sx={{
        height: "calc(100vh)", // let height expand naturally
        paddingTop: "50px", // padding to avoid overlap with app bar
        width: "100%",
        overflow: "hidden",
      }}
    >
      <Stack direction="column">
        <Tabs
          centered
          value={panel}
          aria-label="chat and data tabs"
          onChange={onPanelChange}
        >
          <Tab label="Chat" />
          <Tab label="Grid" />
          <Tab label="Query" />
        </Tabs>
        <Container
          disableGutters
          sx={{
            padding: 0.5,
            height: "calc(100vh)",
            overflow: "auto",
          }}
        >
          <CustomTabPanel value={panel} index={0}>
            <Box>
              <Container
                disableGutters
                ref={contentRef}
                maxWidth="md"
                sx={{ position: "relative", "& .MuiContainer-root": { px: 0 } }}
              >
                <ChatContainer
                  id={id || ""}
                  hasParent={ancestors.length > 0}
                  pendingRequest={pendingRequest}
                  hasData={hasData}
                  metadata={metadata}
                  welcomeMessage={welcomeMessage}
                  suggestedPrompts={suggestedPrompts}
                />
              </Container>
            </Box>
          </CustomTabPanel>
          <CustomTabPanel value={panel} index={1}>
            {hasData && (
              <Box>
                <Container disableGutters maxWidth={false}>
                  <Box ref={gridRef}>
                    {query?.query_id && (
                      <QueryDataGrid
                        queryId={query.query_id}
                        columns={gridColumns}
                        queryMetadata={query}
                        paginate={true}
                        pageSize={100}
                        performanceWarning={performanceWarning}
                        estimatedRows={estimatedRows}
                        estimatedSizeGb={estimatedSizeGb}
                        activeColumn={activeColumn}
                        onActiveColumnChange={setActiveColumn}
                        activeRows={activeRows ?? undefined}
                        onActiveRowsChange={setActiveRows}
                        selectionModel={selectionModel}
                        onSelectionModelChange={setSelectionModel}
                        showAddColumn={true}
                        onAddColumn={handleAddColumn}
                        userEmail={appUser?.email}
                      />
                    )}
                  </Box>
                </Container>
              </Box>
            )}
          </CustomTabPanel>
          <CustomTabPanel value={panel} index={2}>
            <Box
              sx={{
                width: "100%",
                overflow: "auto",
              }}
            >
              <Box
                sx={{
                  "& p": {
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    color: "text.secondary",
                  },
                }}
              >
                <HighlightedSQL
                  code={mergedSql || "No SQL available for this query."}
                />
              </Box>
            </Box>
          </CustomTabPanel>
        </Container>
      </Stack>
    </Box>
  );
};
