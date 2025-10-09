import { LinkRounded, OpenInNew } from "@mui/icons-material";
import { Box, IconButton, Tooltip } from "@mui/material";
import Link from "next/link";
import React from "react";

import {
  isSolanaAddress,
  isSolanaSignature,
  maybeDate,
} from "@/app/helpers/cell";

const handleLinkClick = (e: any) => {
  e.stopPropagation();
};

const floatHints = [
  "amount",
  "balance",
  "price",
  "fee",
  "cost",
  "value",
  "rate",
  "amt",
  "val",
  "cost",
  "p&l",
  "pnl",
  "vol",
  "usd",
];
const intHints = [
  "count",
  "quantity",
  "number",
  "id",
  "index",
  "qty",
  "idx",
  "num",
];

function isDateOnlyUTC(d: Date) {
  return (
    d.getUTCHours() === 0 &&
    d.getUTCMinutes() === 0 &&
    d.getUTCSeconds() === 0 &&
    d.getUTCMilliseconds() === 0
  );
}

export const StyledValue = ({
  columnType,
  value = "",
  params,
  successors,
}: {
  columnType?: string;
  value: string;
  params: any;
  successors?: { name: string; id: string; refs?: any; session_id?: string }[];
}) => {
  // Trim the value to remove extra spaces
  const trimmedValue = (value || "").toString().trim();

  const refRow = successors?.find((s) =>
    (s.refs?.rows || [[]]).find((row: any[]) =>
      row.slice(0, 1).find((rr: any) => Object.values(params.row).includes(rr)),
    ),
  );

  // Check if the trimmed value is a date
  const maybeDateValue = maybeDate(trimmedValue);
  if (columnType?.startsWith("DateTime") ?? maybeDateValue) {
    if (!maybeDateValue) return <span>{value || ""}</span>;

    // const formattedDate = format(maybeDateValue, "MM-dd-yy HH:mm:ss");
    const fullDateTimeOptions = {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
      timeZone: "UTC",
    } as Intl.DateTimeFormatOptions;
    const dayOnlyOptions = {
      year: "numeric",
      month: "long",
      day: "numeric",
    } as Intl.DateTimeFormatOptions;

    const fullDateTime = new Intl.DateTimeFormat([], fullDateTimeOptions);
    const dayOnly = new Intl.DateTimeFormat([], dayOnlyOptions);
    const formattedDate = isDateOnlyUTC(maybeDateValue)
      ? dayOnly.format(maybeDateValue)
      : fullDateTime.format(maybeDateValue);
    // const formattedDate = maybeDateValue.toLocaleString();
    return <span style={{ whiteSpace: "nowrap" }}>{formattedDate}</span>; // Convert to a date
  }

  // Check if the trimmed value is a number
  const maybeNumber = Number(trimmedValue);
  const columnTypeIsNumber =
    columnType?.startsWith("Float") ||
    columnType?.startsWith("Double") ||
    columnType?.startsWith("Int") ||
    columnType?.startsWith("UInt");
  if (columnTypeIsNumber && !Number.isNaN(maybeNumber)) {
    const isFloat =
      columnType?.startsWith("Float") || columnType?.startsWith("Double");
    const isInt =
      columnType?.startsWith("Int") || columnType?.startsWith("UInt");
    return (
      <span
        style={{ display: "inline-block", width: "100%", textAlign: "start" }}
      >
        {isFloat &&
          !isInt &&
          maybeNumber.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}
        {!isFloat &&
          isInt &&
          maybeNumber.toLocaleString(undefined, {
            maximumFractionDigits: 0,
          })}
        {!isFloat && !isInt && maybeNumber.toLocaleString()}
      </span>
    );
  }

  if (isSolanaAddress(trimmedValue)) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          "&:hover .MuiSvgIcon-root": {
            color: (theme) => theme.palette.primary.main,
          },
        }}
      >
        {trimmedValue}
        {refRow && (
          <Tooltip title="Open linked query">
            <IconButton
              component={Link}
              href={`/query/${refRow.session_id}`}
              size="small"
              sx={{ ml: 0 }}
              onClick={handleLinkClick}
            >
              <LinkRounded
                fontSize="small"
                sx={{ color: (theme) => theme.palette.primary.main }}
              />
            </IconButton>
          </Tooltip>
        )}

        <IconButton
          component={Link}
          href={`https://solscan.io/account/${trimmedValue}`}
          size="small"
          sx={{ ml: 0 }}
          onClick={handleLinkClick}
        >
          <Tooltip title="View on Solscan">
            <OpenInNew
              fontSize="small"
              sx={{
                color: "transparent",
                "&:hover": { color: (theme) => theme.palette.primary.main },
              }}
            />
          </Tooltip>
        </IconButton>
      </Box>
    );
  }

  if (isSolanaSignature(trimmedValue)) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          "&:hover .MuiSvgIcon-root": {
            color: (theme) => theme.palette.primary.main,
          },
        }}
      >
        {trimmedValue.slice(0, 8)}...{trimmedValue.slice(-8)}
        <Link
          href={`https://solscan.io/tx/${trimmedValue}`}
          target="_blank"
          passHref
        >
          <IconButton size="small" sx={{ ml: 0 }} onClick={handleLinkClick}>
            <Tooltip title="View on Solscan">
              <OpenInNew
                fontSize="small"
                sx={{
                  color: "transparent",
                  "&:hover": { color: (theme) => theme.palette.primary.main },
                }}
              />
            </Tooltip>
          </IconButton>
        </Link>
      </Box>
    );
  }

  return <span>{value || ""}</span>; // Return as-is if not a date or solana address or number
};
