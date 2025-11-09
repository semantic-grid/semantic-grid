import { Check, ContentCopy } from "@mui/icons-material";
import { Box, IconButton, Tooltip } from "@mui/material";
import { useState } from "react";

import type { TChatSection } from "@/app/lib/types";

const CopyQueryUrl = ({ section }: { section: TChatSection }) => {
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip title="Copy query URL">
      <IconButton
        size="small"
        aria-label="copy query URL"
        onClick={(e) => {
          e.stopPropagation();
          if (typeof window === "undefined") return;

          const url = `${window.location.origin}/q/${section.query?.query_id}`;
          navigator.clipboard
            .writeText(url)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 2000); // Reset copied state after 2 seconds
            })
            .catch((err) => {
              // console.error("Failed to copy URL:", err);
            });
        }}
      >
        <Box
          component={copied ? Check : ContentCopy}
          sx={{
            width: 16,
            height: 16,
            color: "text.secondary",
          }}
        />
      </IconButton>
    </Tooltip>
  );
};

export default CopyQueryUrl;
