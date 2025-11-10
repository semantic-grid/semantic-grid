"use client";

/**
 * NotebookDashboard
 *
 * Split-pane layout for V2 notebook interface.
 * Left: Chat/notebook cells
 * Right: Data visualization (table/charts)
 *
 * Based on InteractiveDashboard structure from /grid/[id]
 */

import { Box, Container, Slide } from "@mui/material";
import { useContext, useEffect, useMemo, useRef, useState } from "react";

import { ThemeContext } from "@/app/contexts/Theme";
import { useLocalStorage } from "@/app/hooks/useLocalStorage";
import { useMessageSession } from "@/app/contexts/v2/MessageSession";

import { NotebookChatPane } from "./notebook-chat-pane";

export interface NotebookDashboardProps {
  sessionId: string;
}

export const NotebookDashboard = ({ sessionId }: NotebookDashboardProps) => {
  const { messages } = useMessageSession();
  const { mode, isLarge } = useContext(ThemeContext);

  const [leftWidth, setLeftWidth] = useLocalStorage<string>(
    `nb-left-width-${sessionId}`,
    "",
  );
  const [maxLeftWidth, setMaxLeftWidth] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const prevX = useRef<number | null>(null);
  const maxLeftWidthRef = useRef<number | null>(null);

  // Determine if we have data to show on the right
  const hasData = useMemo(() => {
    // Check if any assistant message has data/results
    return messages.some(
      (m) => m.role === "assistant" && m.metadata?.has_results,
    );
  }, [messages]);

  const showGrid = hasData;

  useEffect(() => {
    if (!showGrid) {
      setLeftWidth(""); // Reset left width if no data
    } else if (showGrid && !leftWidth) {
      setLeftWidth((window.innerWidth / 3).toString()); // Default to 1/3 of the window width
    }
  }, [showGrid, leftWidth]);

  useEffect(() => {
    maxLeftWidthRef.current = maxLeftWidth;
  }, [maxLeftWidth]);

  useEffect(() => {
    if (contentRef.current) {
      const scrollWidth = window.innerWidth - 300; // Adjust as needed
      setMaxLeftWidth(scrollWidth);
    }
  }, [messages, contentRef]);

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
    prevX.current = null;
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

  return isLarge ? (
    <Box
      ref={containerRef}
      sx={{
        height: showGrid ? "calc(100vh - 64px)" : "auto",
        display: "flex",
        flexDirection: "row",
        width: "100%",
        position: "relative",
        justifyContent: "center",
        overflowX: "hidden",
        overflowY: showGrid ? "auto" : "visible",
      }}
    >
      {/* Left pane - chat/notebook */}
      <Box
        sx={{
          width: showGrid ? `${leftWidth}px` : "100%",
          maxWidth: showGrid && maxLeftWidth ? `${maxLeftWidth}px` : "100%",
          flexGrow: showGrid ? 1 : 0,
          flexBasis: showGrid ? leftWidth : "auto",
          overflow: "visible",
          display: "flex",
          flexDirection: "column",
          position: "relative",
          height: "100%",
        }}
      >
        <Container
          ref={contentRef}
          maxWidth="lg"
          sx={{
            position: "relative",
            "& .MuiContainer-root": { px: 0 },
            height: "100%",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <NotebookChatPane sessionId={sessionId} />
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

      {/* Right panel - data visualization */}
      {showGrid && (
        <Box
          sx={{
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
              timeout={400}
            >
              <Box
                sx={{
                  height: "calc(100vh - 64px)",
                  position: "relative",
                  overflow: "auto",
                }}
              >
                {/* TODO: Add data visualization components here */}
                <Box sx={{ p: 3, color: "text.secondary" }}>
                  Data visualization will appear here
                </Box>
              </Box>
            </Slide>
          </Container>
        </Box>
      )}
    </Box>
  ) : (
    // Mobile/small screen - simple single column
    <Box
      ref={containerRef}
      sx={{
        height: "calc(100vh)",
        paddingTop: "50px",
        width: "100%",
        overflow: "hidden",
      }}
    >
      <Container
        disableGutters
        sx={{
          padding: 0.5,
          height: "calc(100vh)",
          overflow: "auto",
        }}
      >
        <NotebookChatPane sessionId={sessionId} />
      </Container>
    </Box>
  );
};
