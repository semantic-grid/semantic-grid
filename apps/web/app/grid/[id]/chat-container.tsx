"use client";

import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import {
  alpha,
  Box,
  Container,
  Fab,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ResponseTextMessage } from "@/app/components/chat-box/ResponseTextMessage";
import { ResponseTextStatus } from "@/app/components/chat-box/ResponseTextStatus";
import CopyQueryUrl from "@/app/components/CopyQueryUrl";
import SaveQueryUrl from "@/app/components/SaveQueryUrl";
import ShareQueryUrl from "@/app/components/ShareQueryUrl";
import { useGridSession } from "@/app/contexts/GridSession";
import { ThemeContext } from "@/app/contexts/Theme";
import { StructuredText } from "@/app/helpers/text";
import { getNewSessionWelcome, getSuggestedPrompts } from "@/app/lib/payload";
import type { SuggestedPrompt } from "@/app/lib/payload-types";
import { getSuggestions } from "@/app/lib/suggestions";
import type { TChatMessage, TChatSection } from "@/app/lib/types";

import { QueryBox } from "./query-box";

const rows = (count: number | undefined) =>
  count ? ` ${count?.toLocaleString()} rows` : "";

const isVisible = (text: string | undefined = "") =>
  text !== "Starting from existing query";

export const ChatContainer = ({
  id,
  newCol,
  gridColumns,
  hasParent = false,
  pendingRequest,
  // rowCount,
  hasData = false, // added to handle no data case
  metadata, // metadata for follow-ups
  // data, // data for the table, if needed
}: {
  id: string;
  newCol?: boolean;
  gridColumns?: any[];
  hasParent?: boolean;
  pendingRequest?: any;
  // rowCount?: number;
  metadata?: any; // metadata for follow-ups
  hasData?: boolean; // added to handle no data case
}) => {
  const { mode, isLarge } = useContext(ThemeContext);
  const {
    pending,
    activeColumn,
    activeRows,
    handleClick,
    handleKeyDown,
    handleChange,
    onSelectColumn,
    sects,
    scrollRef,
    setPromptVal,
    isLoading,
    isValidating,
    requestId,
    setRequestId,
  } = useGridSession();
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  // const [followUps, setFollowUps] = useState<string[]>([]);
  const [showButton, setShowButton] = useState(false);
  const [inputHeight, setInputHeight] = useState(0);

  const [welcome, setWelcome] = useState<string>("");
  useEffect(() => {
    getNewSessionWelcome().then(setWelcome);
  }, []);

  const [followUps, setFollowUps] = useState<string[]>([]);
  useEffect(() => {
    getSuggestedPrompts()
      .then((p) => p.map((p: SuggestedPrompt) => p.text))
      .then(setFollowUps);
  }, []);

  useEffect(() => {
    const isInternalScroll = hasData;
    const scrollNode = isInternalScroll ? scrollRef.current : window;
    const observeNode = isInternalScroll ? scrollRef.current : document.body;

    if (!scrollNode || !observeNode) return;

    const updateScrollState = () => {
      const scrollTop = isInternalScroll
        ? (scrollRef.current?.scrollTop ?? 0)
        : window.scrollY;

      const scrollHeight = isInternalScroll
        ? (scrollRef.current?.scrollHeight ?? 0)
        : document.documentElement.scrollHeight;

      const clientHeight = isInternalScroll
        ? (scrollRef.current?.clientHeight ?? 0)
        : window.innerHeight;

      // Show FAB if not scrolled to bottom-ish
      setShowButton(scrollHeight - scrollTop - clientHeight > 80);
    };

    const scrollToBottom = () => {
      if (isInternalScroll && scrollRef.current) {
        scrollRef.current.scrollTo({
          top: scrollRef.current.scrollHeight,
          behavior: "smooth",
        });
      } else {
        window.scrollTo({
          top: document.documentElement.scrollHeight,
          behavior: "smooth",
        });
      }
    };

    const handleScroll = () => {
      updateScrollState();
    };

    // Attach scroll + resize listeners
    scrollNode.addEventListener("scroll", handleScroll);
    window.addEventListener("resize", handleScroll);

    // Attach ResizeObserver to detect content growth
    const observer = new ResizeObserver(() => {
      scrollToBottom();
      updateScrollState();
    });
    observer.observe(observeNode);

    // Trigger initial scroll + visibility check
    scrollToBottom();
    updateScrollState();

    // eslint-disable-next-line consistent-return
    return () => {
      scrollNode.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleScroll);
      observer.disconnect();
    };
  }, [hasData]);

  const suggestions = useCallback(async () => {
    // console.log("suggestions", metadata, sects);
    if (!metadata && !pending && !hasData && !pendingRequest) {
      const ss = await getSuggestions(
        null,
        metadata,
        undefined,
        undefined,
        "Suggest 3 starter queries for a user willing to explore copy trading on Solana",
      );
      // setFollowUps(ss);
    }
  }, []);

  useEffect(() => {
    console.log("pending", pendingRequest);
  }, [pendingRequest]);

  useEffect(() => {
    if (newCol && inputRef.current) {
      inputRef.current.focus();
      // setPrompt("");
    } else if (inputRef.current) {
      inputRef.current.blur();
      // console.log("removing new column");
      // setSects((ss) =>
      //  ss.filter((s) => s.id !== "new_column" || s.label !== "New column"),
      // );
    }
  }, [newCol]);

  useEffect(() => {
    // on page load, set requestId to the last one in the sections
    if (sects.length > 0) {
      const lastSection = sects[sects.length - 1];
      if (lastSection?.requestId && !requestId) {
        setRequestId(lastSection.requestId);
        // eslint-disable-next-line no-restricted-globals
        history.pushState(null, "", `#${lastSection.requestId}`);
      }
    }
  }, [sects]);

  const handleSectionClick = (section: TChatSection) => {
    console.log("section selected", requestId, section);

    // onSelectColumn({ field: section.id, headerName: section.label });
    const el = section.requestId
      ? document.getElementById(section.requestId)
      : null;
    if (el) {
      if (requestId !== section.requestId) {
        // disabled scrolling for now
        // el.scrollIntoView({ behavior: "smooth", block: "start" });

        if (section.query) {
          // Update URL fragment without reloading
          // eslint-disable-next-line no-restricted-globals
          history.pushState(null, "", `#${section.requestId}`);
          setRequestId(section.requestId);
        }
      } else if (!!requestId && requestId === section.requestId) {
        // eslint-disable-next-line no-restricted-globals
        // history.pushState(null, "", `/grid/${id}`);
        // setRequestId(undefined);
      }
    }
  };

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;

    // FilledInput wraps the textarea inside .MuiFilledInput-input
    const textarea =
      node.tagName === "TEXTAREA" ? node : node.querySelector("textarea");

    if (!textarea) return;

    const resizeObserver = new ResizeObserver((entries) => {
      // eslint-disable-next-line no-restricted-syntax
      for (const entry of entries) {
        const { height } = entry.contentRect;
        setInputHeight(height);
      }
    });

    resizeObserver.observe(textarea);

    // eslint-disable-next-line consistent-return
    return () => resizeObserver.disconnect();
  }, []);

  const fabStyles = useMemo(
    () => ({
      position: "absolute",
      bottom: `calc(${inputHeight}px + 6rem)`,
      left: "50%",
      transform: "translateX(-50%)",
      zIndex: 1000,
    }),
    [inputHeight],
  );

  const getBgColor = (msg: { isBot: boolean }) => {
    if (!msg.isBot) return mode === "dark" ? "grey.800" : "#E9e8e6";
    return "unset";
  };

  const context = () => {
    // console.log("ctx", activeRows);
    if (activeColumn?.field === "__add_column__")
      return `${activeColumn?.headerName}` || "New column";
    if (activeColumn && activeColumn.headerName !== "General")
      return `Column: ${activeColumn?.headerName}` || "";
    if (activeRows) {
      if (activeRows.length > 1) return `Rows: ${activeRows.length}`;
      if (activeRows.length === 1 && activeRows[0]?.wallet)
        return (
          `Wallet: ${activeRows[0]?.wallet}` ||
          `${gridColumns?.[0]?.headerName}: ${Object.values(activeRows[0])[0]}`
        );
      if (Object.values(activeRows)[0])
        return `${gridColumns?.[0]?.headerName}: ${Object.values(activeRows[0] || {})[0] || "-"}`;
      return "Row";
    }
    return "General";
  };

  const isEmptyChat = useMemo(
    () =>
      !metadata &&
      !pending &&
      !isLoading &&
      !isValidating &&
      sects?.length === 0,
    [metadata, pending, isLoading, isValidating, sects],
  );
  // console.log("isEmptyChat", isEmptyChat);

  return (
    <Paper
      elevation={0}
      sx={{
        px: 0,
        mt: hasData ? 0 : 0, // add margin-top only when no data
        pt: hasData ? 1 : 1, // add margin-top only when no data
        // mb: 2,
        // eslint-disable-next-line no-nested-ternary
        height: isLarge
          ? hasData
            ? "calc(100vh - 64px)" // constrained when in split view
            : "auto"
          : "calc(100vh - 92px)", // allow full window scroll
        overflow: "visible", // allow inner content to expand
        position: "relative",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Box ref={scrollRef} sx={{ overflowY: "auto" }}>
        <Box sx={{ flex: 1, pr: 1, pb: `calc(${inputHeight}px + 10rem)` }}>
          {sects.map((section: TChatSection, idx: number) => (
            // const isActive = activeColumn?.field === section.id;
            // const isGeneral = section.id === "general";

            <Box key={`${section.id}_${idx.toString()}`} sx={{ mb: 0 }}>
              <Box
                sx={{
                  p: 1,
                  position: "relative",
                  transition: "background-color 0.2s ease",
                  borderRadius: "12px",
                  backgroundColor: (theme) =>
                    Boolean(requestId) && section.requestId === requestId
                      ? alpha(
                          mode === "dark"
                            ? theme.palette.grey["800"]
                            : theme.palette.grey["200"],
                          0.5,
                        )
                      : "transparent",
                }}
                id={section.requestId}
                onClick={() => handleSectionClick(section)}
              >
                {section.messages?.map(
                  (msg: TChatMessage, i: number, arr: TChatMessage[]) => (
                    <Box key={`${msg.uid}-${i.toString()}`}>
                      <Box
                        sx={{
                          display: "flex",
                          justifyContent: i % 2 === 0 ? "end" : "start",
                        }}
                      >
                        <Box
                          sx={{
                            borderRadius: "12px",
                            padding: 2,
                            pb: i % 2 === 0 ? 2 : 0.5,
                            bgcolor: getBgColor({ isBot: i % 2 !== 0 }),
                            width: "fit-content",
                            display: isVisible(msg.text) ? "block" : "none",
                          }}
                        >
                          {i % 2 === 0 && (
                            <Box>
                              <Typography
                                variant="body2"
                                sx={{ width: "fit-content" }}
                              >
                                {StructuredText(msg.text || "")}
                              </Typography>
                            </Box>
                          )}
                          {i % 2 !== 0 && (
                            <Box
                              sx={{
                                marginBottom:
                                  i === arr.length - 1 &&
                                  idx === sects.length - 1
                                    ? 0
                                    : 0,
                                maxWidth: "100%",
                                overflowX: "hidden",
                                "&  li": {
                                  marginLeft: "1rem",
                                },
                                "& > *": {
                                  maxWidth: "100%",
                                  whiteSpace: "normal", // prevents nowrap behavior
                                },
                              }}
                            >
                              <ResponseTextMessage
                                text={msg.text}
                                status={section.status}
                                linkedSession={section.linkedSession}
                              />
                              <ResponseTextStatus
                                status={section.status}
                                rowCount={metadata?.row_count}
                                isLoading={isLoading}
                                lastMessage={
                                  i === arr.length - 1 &&
                                  idx === sects.length - 1
                                }
                              />
                            </Box>
                          )}
                          {i % 2 !== 0 &&
                            section.query &&
                            Boolean(requestId) &&
                            section.requestId === requestId && (
                              <Stack
                                sx={{ width: "100%", mt: 0.5 }}
                                direction="row"
                                spacing={1}
                                alignItems="center"
                                justifyContent="space-between"
                              >
                                <Typography
                                  variant="body2"
                                  color="textSecondary"
                                >
                                  {rows(section.query?.row_count)}
                                </Typography>
                                <Box>
                                  <CopyQueryUrl section={section} />
                                  <ShareQueryUrl section={section} />
                                  <SaveQueryUrl section={section} />
                                </Box>
                              </Stack>
                            )}
                        </Box>
                      </Box>
                    </Box>
                  ),
                )}
              </Box>
            </Box>
          ))}
        </Box>
        <Box
          sx={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            // padding: 2,
            pb: 0,
            background: (theme) => theme.palette.background.paper,
          }}
        >
          <Box
            sx={{
              position: hasData ? "static" : "fixed",
              bottom: isEmptyChat ? "30vh" : 0,
              left: 0,
              width: "100%",
              zIndex: 1000,
              bgcolor: "background.paper",
              px: 0,
              py: 2,
            }}
          >
            <Container maxWidth="md">
              <Stack
                direction="column"
                spacing={1}
                mb={1}
                justifyContent="space-between"
                sx={{ px: 2 }}
              >
                {isEmptyChat && (
                  <Typography variant="body2" color="textSecondary">
                    {welcome}
                  </Typography>
                )}
                {isEmptyChat &&
                  followUps.map((f: string) => (
                    <Box
                      key={f}
                      onClick={() => {
                        setPromptVal(f);
                        // setVal(f);
                      }}
                      sx={{
                        cursor: "pointer",
                        // maxWidth: `${100 / (TutorialSteps[Number(step)]?.choices?.length || 1)}%`,
                        transition: "all 0.2s ease-in-out",
                        border: `1px solid ${alpha(mode === "dark" ? "#fff" : "#000", 0.5)}`,
                        "&:hover": {
                          border: `1px solid ${alpha(mode === "dark" ? "#fff" : "#000", 0.8)}`,
                        },
                        borderRadius: "8px",
                        padding: 2,
                      }}
                    >
                      <Stack direction="column">
                        <Typography
                          variant="body2"
                          sx={{
                            transition: "all 0.2s ease-in-out",
                            color: alpha(
                              mode === "dark" ? "#fff" : "#000",
                              0.5,
                              // val === f ? 0.8 : 0.5,
                            ),
                            "&:hover": {
                              color: alpha(
                                mode === "dark" ? "#fff" : "#000",
                                0.8,
                              ),
                            },
                          }}
                        >
                          {f}
                        </Typography>
                      </Stack>
                    </Box>
                  ))}
              </Stack>
              <QueryBox
                id={id}
                hasData={hasData}
                formRef={formRef}
                inputRef={inputRef}
                handleClick={handleClick(inputRef, formRef, id)}
                handleKeyDown={handleKeyDown(inputRef, formRef, id)}
                handleChange={handleChange(inputRef)}
              />
              <Fab
                sx={{
                  visibility: showButton ? "visible" : "hidden",
                  opacity: showButton ? 1 : 0,
                  bgcolor:
                    mode === "dark"
                      ? alpha("#424242", 0.8)
                      : alpha("#E9e8e6", 0.5),
                  boxShadow: "none", // Remove shadow
                  "&:hover": {
                    bgcolor:
                      mode === "dark" ? alpha("#424242", 0.8) : undefined,
                    boxShadow: "none", // Remove shadow on hover
                  },
                }}
                size="small"
                onClick={() => {
                  if (hasData) {
                    scrollRef.current?.scrollTo({
                      top: scrollRef.current.scrollHeight,
                      behavior: "smooth",
                    });
                  } else {
                    window.scrollTo({
                      top: document.documentElement.scrollHeight,
                      behavior: "smooth",
                    });
                  }
                }}
                style={fabStyles as any}
                aria-label="Scroll to Bottom"
              >
                <KeyboardArrowDownIcon />
              </Fab>
            </Container>
          </Box>
        </Box>
      </Box>
    </Paper>
  );
};
