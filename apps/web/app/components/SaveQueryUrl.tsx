import { Check } from "@mui/icons-material";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import { Box, IconButton, Menu, MenuItem, Tooltip } from "@mui/material";
import React, { useState } from "react";

import { addQueryToUserDashboard } from "@/app/actions";
import type { TChatSection } from "@/app/lib/types";

const SaveQueryUrl = ({ section }: { section: TChatSection }) => {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [saved, setSaved] = useState(false);

  const open = Boolean(anchorEl);

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    event.stopPropagation();
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleSelect = async (type: "table" | "chart") => {
    const queryUid = section.query?.query_id;
    console.log("save query Uid", queryUid, "as", type);
    if (!queryUid) return;

    await addQueryToUserDashboard({ queryUid, itemType: type });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000); // Reset copied state after 2 seconds
    setAnchorEl(null);
  };

  return (
    <>
      <Tooltip title="Add to user dashboard">
        <IconButton size="small" aria-label="save query" onClick={handleClick}>
          <Box
            component={saved ? Check : PlaylistAddIcon}
            sx={{
              width: 16,
              height: 16,
              color: "text.secondary",
            }}
          />
        </IconButton>
      </Tooltip>

      <Menu
        anchorEl={anchorEl}
        open={open}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        transformOrigin={{ vertical: "top", horizontal: "center" }}
        onClose={handleClose}
        onClick={(e) => e.stopPropagation()} // prevent bubbling to parent
      >
        <MenuItem onClick={() => handleSelect("table")}>Table</MenuItem>
        <MenuItem onClick={() => handleSelect("chart")}>Chart</MenuItem>
      </Menu>
    </>
  );
};

export default SaveQueryUrl;
