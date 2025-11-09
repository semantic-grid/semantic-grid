import { Box, IconButton, Tooltip } from "@mui/material";
import React from "react";

import ShareQuery from "@/app/icons/share.svg";
import type { TChatSection } from "@/app/lib/types";

const ShareQueryUrl = ({ section }: { section: TChatSection }) => (
  <Tooltip title="Share query">
    <IconButton
      size="small"
      aria-label="open query"
      onClick={(event) => {
        event.stopPropagation();
        // use navigator share API if available
        if (typeof navigator !== "undefined" && navigator.share) {
          navigator
            .share({
              url: `/q/${section.query?.query_id}`,
            })
            .catch((err) => {
              console.error("Error sharing:", err);
            });
        }
      }}
    >
      <Box
        component={ShareQuery}
        sx={{
          width: 16,
          height: 16,
          color: "text.secondary",
        }}
      />
    </IconButton>
  </Tooltip>
);

export default ShareQueryUrl;
