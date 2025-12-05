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

  const { view, setView, chartType, setChartType } = ctx;

  if (!isItemPage) return null;

  const handleChartButtonClick = (event: React.MouseEvent<HTMLElement>) => {
    // If already in chart view, open menu to change chart type
    if (view === "chart") {
      setChartMenuAnchor(event.currentTarget);
    } else {
      // Otherwise, switch to chart view
      setView("chart");
    }
  };

  const handleChartTypeSelect = (type: ChartType) => {
    console.log("select chart type", type);
    setChartType(type);
    setChartMenuAnchor(null);
  };

  const handleCloseMenu = () => {
    setChartMenuAnchor(null);
  };

  return (
    <>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={view}
        onChange={(_, next: ViewKey) => {
          console.log(
            "ToggleButtonGroup onChange:",
            next,
            "current view:",
            view,
          );
          // Only handle grid/sql here - chart is handled by onClick
          if (next && next !== "chart") {
            setView(next);
          }
        }}
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
          onClick={handleChartButtonClick}
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
        <MenuItem
          selected={chartType === "pie"}
          onClick={() => handleChartTypeSelect("pie")}
        >
          Pie Chart
        </MenuItem>
        <MenuItem
          selected={chartType === "line"}
          onClick={() => handleChartTypeSelect("line")}
        >
          Line Chart
        </MenuItem>
        <MenuItem
          selected={chartType === "bar"}
          onClick={() => handleChartTypeSelect("bar")}
        >
          Bar Chart
        </MenuItem>
      </Menu>
    </>
  );
};
