import { LinkRounded, OpenInNew } from "@mui/icons-material";
import { Box, IconButton, Stack, Tooltip } from "@mui/material";
import Link from "next/link";
import React from "react";
import Markdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";

import { structuredText } from "@/app/helpers/text";

const remapAnchor = ({ children, href, ...props }: any) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      {...props}
      style={{ textDecoration: "none", color: "inherit" }}
    >
      {children}
    </a>
    <Tooltip title="View on Solscan">
      <IconButton
        component="a"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        size="small"
        sx={{ p: 0.5 }}
      >
        <OpenInNew
          fontSize="small"
          sx={{ color: (theme) => theme.palette.primary.main }}
        />
      </IconButton>
    </Tooltip>
  </span>
);

export const ResponseTextMessage = ({
  text,
  status,
  linkedSession,
}: {
  text?: string;
  status?: string;
  linkedSession?: string; // whether to show the link icon
}) => (
  <Box
    sx={{
      "& *": {
        fontSize: "1rem",
        border: "none",
        fontFamily: (theme) => theme.typography.fontFamily,
      },
      display: "inline-block",
      "&:hover .hover-span": {
        visibility: "visible",
      },
    }}
  >
    {text && status === "Error" && (
      <Box
        sx={{
          color: "text.secondary",
          fontSize: "0.875rem",
        }}
      >
        <Box component="span" sx={{ color: "error.main", fontWeight: 500 }}>
          Error:
        </Box>{" "}
        {text}
      </Box>
    )}
    {text && status !== "Error" && (
      <Box sx={{ "& a:hover": { color: "primary.main" } }}>
        {!linkedSession && (
          <Markdown
            key={text?.slice(0, 32)}
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
            components={{
              a: remapAnchor,
            }}
          >
            {structuredText(text)}
          </Markdown>
        )}
        {linkedSession && (
          <Stack direction="row" alignItems="center">
            <Markdown
              key={text?.slice(0, 32)}
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
            >
              Created linked query {/* text */}
            </Markdown>
            <Tooltip title="Open linked query">
              <Link href={`/grid/${linkedSession}`}>
                <LinkRounded
                  sx={{
                    ml: 0.5,
                    verticalAlign: "middle",
                    // "&:hover": {
                    color: (theme) => theme.palette.primary.main,
                    // },
                  }}
                />
              </Link>
            </Tooltip>
          </Stack>
        )}
      </Box>
    )}
  </Box>
);
