import { Menu, MenuItem, ToggleButton, ToggleButtonGroup } from "@mui/material";
import { usePathname } from "next/navigation";
import React, { useState } from "react";

import { useItemViewContext } from "@/app/contexts/ItemView";

type ViewKey = "chart" | "grid" | "sql";
const VIEW_KEYS: ViewKey[] = ["chart", "grid", "sql"];

type ChartType = "pie" | "line" | "bar";

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  pie: "Pie",
  line: "Line",
  bar: "Bar",
};

export const ItemViewSwitcher = () => {
  const pathname = usePathname();
  const isItemPage =
    pathname?.startsWith("/item/") || pathname?.startsWith("/grid/");
  const ctx = useItemViewContext();

  const [chartMenuAnchor, setChartMenuAnchor] = useState<null | HTMLElement>(
    null,
  );

  if (!ctx) return null; // not on /item/[id]

  const { view, setView, chartType, setChartType, availableChartTypes } = ctx;

  if (!isItemPage) return null;

  // Only show chart types that are available for this data
  const filteredChartTypes = availableChartTypes || ["line", "bar", "pie"];

  const handleChartTypeSelect = (type: ChartType) => {
    console.log("select chart type", type);
    setChartType(type);
    setChartMenuAnchor(null);
  };

  const handleCloseMenu = () => {
    setChartMenuAnchor(null);
  };

  const handleViewChange = (
    _event: React.MouseEvent<HTMLElement>,
    next: ViewKey | null,
  ) => {
    console.log("ToggleButtonGroup onChange:", next, "current view:", view);
    // Handle all view changes here
    if (next) {
      setView(next);
    }
  };

  return (
    <>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={view}
        onChange={handleViewChange}
        aria-label="Item view"
        sx={{
          // Make it look like it belongs in the toolbar
          borderRadius: 999,
          "& .MuiToggleButton-root": {
            textTransform: "none",
            px: 1.5,
          },
        }}
      >
        <ToggleButton
          value="chart"
          aria-label="Chart view"
          onClick={(e) => {
            // If already in chart view, open menu to change chart type
            // Don't prevent default - let onChange handle the view switch
            if (view === "chart") {
              e.stopPropagation(); // Prevent onChange from firing
              setChartMenuAnchor(e.currentTarget);
            }
          }}
        >
          {CHART_TYPE_LABELS[chartType]} Chart
        </ToggleButton>
        <ToggleButton value="grid" aria-label="Table view">
          Table
        </ToggleButton>
        <ToggleButton value="sql" aria-label="SQL view">
          SQL
        </ToggleButton>
      </ToggleButtonGroup>

      <Menu
        anchorEl={chartMenuAnchor}
        open={Boolean(chartMenuAnchor)}
        onClose={handleCloseMenu}
        anchorOrigin={{
          vertical: "bottom",
          horizontal: "left",
        }}
        transformOrigin={{
          vertical: "top",
          horizontal: "left",
        }}
        slotProps={{
          paper: {
            sx: {
              mt: 0.5,
              borderRadius: 2,
            },
          },
        }}
      >
        {filteredChartTypes.map((type) => (
          <MenuItem
            key={type}
            selected={chartType === type}
            onClick={() => handleChartTypeSelect(type)}
          >
            {CHART_TYPE_LABELS[type]} Chart
          </MenuItem>
        ))}
      </Menu>
    </>
  );
};
