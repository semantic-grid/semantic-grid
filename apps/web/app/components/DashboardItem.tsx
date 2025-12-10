"use client";

import {
  Card,
  CardActionArea,
  CardContent,
  Stack,
  Typography,
} from "@mui/material";
import { saveAs } from "file-saver";
import Link from "next/link";
import { useContext } from "react";

import { DashboardChartItem } from "@/app/components/DashboardChartItem";
import { DashboardItemMenu } from "@/app/components/DashboardItemMenu";
import { DashboardTableItem } from "@/app/components/DashboardTableItem";
import { useData } from "@/app/contexts/DataContext";
import { ThemeContext } from "@/app/contexts/Theme";
import { useQueryObject } from "@/app/hooks/useQueryObject";

const exportRowsAsCSV = (rows: any[]) => {
  if (rows.length === 0) return;

  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(","),
    ...rows.map((row) =>
      headers.map((field) => JSON.stringify(row[field] ?? "")).join(","),
    ),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  saveAs(blob, "selected-rows.csv");
};

const DashboardCard = ({
  id,
  title,
  href,
  type,
  subtype,
  queryUid,
  slugPath,
  maxItemsPerRow,
}: {
  id: string;
  title: string;
  queryUid?: string;
  href?: string;
  type?: string;
  subtype?: string;
  slugPath: string;
  maxItemsPerRow: number;
}) => {
  const { data: query } = useQueryObject(queryUid!);
  const { fetchQuery, getQueryState } = useData();
  const { isLarge } = useContext(ThemeContext);
  const minHeight = maxItemsPerRow ? 400 * (3 / maxItemsPerRow) : 400;

  // Get data from DataContext
  const queryState = queryUid ? getQueryState(queryUid) : null;
  const data = queryState ? { rows: queryState.rows } : null;
  const fetchedAt = queryState?.cachedAt;

  // Refresh using DataContext with force flag
  const refresh = () => {
    if (queryUid) {
      fetchQuery(queryUid, { force: true, pageSize: 100, paginate: false });
    }
  };

  // Refresh with email notification
  const refreshWithNotify = () => {
    if (queryUid) {
      fetchQuery(queryUid, {
        force: true,
        pageSize: 100,
        paginate: false,
        notify: true,
      });
    }
  };

  // Check if query has performance warning
  const performanceWarning = query?.explanation?.performance_warning ?? false;

  const onCopyUrl = async () => {
    if (!queryUid) return;
    const url = `${window.location.origin}/q/${queryUid}`;
    await navigator.clipboard.writeText(url);
  };

  const onDownloadCsvVisible = async () => {
    if (!queryUid || !data) return;
    exportRowsAsCSV(data?.rows);
  };

  const inner = (
    <Card
      elevation={0}
      sx={
        {
          // minHeight: 400,
          // minWidth: 400,
          // width: 400,
        }
      }
    >
      <CardActionArea
        component={href ? Link : "div"}
        href={href}
        sx={{ p: isLarge ? 2 : 0.5 }}
        disableRipple
      >
        <CardContent sx={isLarge ? {} : { p: 1, "&:last-child": { pb: 1 } }}>
          <Stack spacing={1} justifyContent="center">
            {type !== "create" && (
              <Stack
                direction="row"
                alignItems="top"
                justifyContent="space-between"
              >
                <Typography variant="body1" color="text.primary" gutterBottom>
                  {title || query?.summary}
                </Typography>
                {query && (
                  <DashboardItemMenu
                    id={id}
                    query={query}
                    slugPath={slugPath}
                    refresh={refresh}
                    refreshWithNotify={refreshWithNotify}
                    fetchedAt={fetchedAt || undefined}
                    onDownloadCsvFull={async () => {}}
                    onDownloadCsvVisible={onDownloadCsvVisible}
                    onCopyUrl={onCopyUrl}
                    performanceWarning={performanceWarning}
                  />
                )}
              </Stack>
            )}
            {type === "create" && (
              <Stack
                direction="column"
                alignItems="center"
                justifyContent="center"
                spacing={2}
                sx={{ flexGrow: 1, opacity: 0.5, height: minHeight }}
              >
                <Typography
                  variant="h1"
                  component="div"
                  sx={{ fontSize: 64, lineHeight: 1 }}
                >
                  +
                </Typography>
                <Typography variant="body1">Add New</Typography>
              </Stack>
            )}
            {type === "chart" && queryUid && (
              <DashboardChartItem
                queryUid={queryUid}
                chartType={subtype || "pie"}
                minHeight={minHeight}
              />
            )}
            {type === "table" && queryUid && (
              <DashboardTableItem queryUid={queryUid} minHeight={minHeight} />
            )}
          </Stack>
        </CardContent>
      </CardActionArea>
    </Card>
  );

  return inner;
};

export default DashboardCard;
