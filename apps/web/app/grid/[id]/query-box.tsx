import styled from "@emotion/styled";
import { ArrowUpward, Stop, Tune } from "@mui/icons-material";
import ClearIcon from "@mui/icons-material/Clear";
import {
  alpha,
  Autocomplete,
  Box,
  Chip,
  Divider,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Popper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Toolbar,
  Tooltip,
} from "@mui/material";
import React, { useCallback, useContext, useEffect, useState } from "react";

import { updateRequest } from "@/app/actions";
import { options } from "@/app/contexts/ChatSession";
import { useGridSession } from "@/app/contexts/GridSession";
import { ThemeContext } from "@/app/contexts/Theme";
import { isSolanaAddress, isSolanaSignature } from "@/app/helpers/cell";

const Instruments = ({ selectedAction, setSelectedAction }: any) => (
  <ToggleButtonGroup
    exclusive
    value={selectedAction}
    onChange={(e, val) => {
      if (!val) return; // Prevent setting to null
      setSelectedAction(val as keyof typeof options);
    }}
  >
    {Object.entries(options).map(([k, option]) => (
      <Tooltip title={option.label} key={k}>
        <ToggleButton
          value={k}
          key={k}
          sx={{
            py: 0,
            border: "none",
            "&.Mui-selected": { backgroundColor: "transparent" },
            "&:hover": {
              backgroundColor: "transparent", // disables background on hover
            },
            "&.Mui-selected:hover": {
              backgroundColor: "transparent", // also disables background when selected + hover
            },
          }}
        >
          {React.cloneElement(option.icon, {
            color: selectedAction === k ? "primary" : "action",
          })}
        </ToggleButton>
      </Tooltip>
    ))}
  </ToggleButtonGroup>
);

const StyledPopper = styled(Popper)(({ theme }) => ({
  // backgroundColor: "#1f1e1d", // your desired background
  padding: "4px",
  borderRadius: 0,
  border: "none",
  zIndex: 1300,
  elevation: 0,
}));

const enrichedContext = (selectedAction: string, context: string) => {
  if (context && context !== "General") {
    const contextParts = context.split(" ");
    const processedContextParts = contextParts.map((part) => {
      if (isSolanaAddress(part)) {
        return `${part.slice(0, 4)}...${part.slice(-4)}`;
      }
      if (isSolanaSignature(part)) {
        return `${part.slice(0, 8)}...${part.slice(-8)}`;
      }
      return part;
    });
    const processedContext = processedContextParts.join(" ");
    const actionLabel =
      (options[selectedAction || ""] || {})?.label || selectedAction;
    return `${actionLabel} ${processedContext}`;
  }
  return "";
};

export const QueryBox = ({
  id,
  formRef,
  handleClick,
  inputRef,
  handleKeyDown,
  handleChange,
  hasData,
}: {
  id: string;
  formRef: React.RefObject<HTMLFormElement>;
  handleClick: (e: React.MouseEvent<any>) => void;
  inputRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement>;
  hasData?: boolean;
  handleKeyDown: (
    e: React.KeyboardEvent<
      HTMLInputElement | HTMLTextAreaElement | HTMLDivElement
    >,
  ) => void;
  handleChange: (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => void;
}) => {
  const { mode } = useContext(ThemeContext);
  const {
    promptVal,
    setPromptVal,
    onSelectColumn,
    onSelectRow,
    pending,
    metadata,
    context,
    placeholder,
    sections,
    activeColumn,
    activeRows,
    lastMessages,
    isLoading,
    isValidating,
    cancelDataFetch,
    selectedAction,
    setSelectedAction,
  } = useGridSession();
  const [focused, setFocused] = useState(false);
  const [followUps, setFollowUps] = useState<string[]>([]);

  useEffect(() => {
    if (!promptVal) {
      setFocused(false);
      setFollowUps([]);
    } else if (promptVal && !focused) {
      setFocused(true);
    }
  }, [promptVal, focused]);

  const suggestions = useCallback(async () => {
    /*
    if (metadata && sections && focused) {
      const ss = await getSuggestions(
        sections.flatMap(
          (s: any) =>
            s?.chat?.map((m: any, idx: number) => ({
              content: m,
              role: idx % 2 === 0 ? "user" : "assistant",
            })) || [],
        ),
        metadata,
        activeRows,
        activeColumn?.headerName,
      );
      setFollowUps(ss);
    }
    */
  }, [activeColumn, activeRows, metadata, sections, focused]);

  useEffect(() => {
    suggestions();
  }, [suggestions]);

  useEffect(() => {
    if (promptVal && inputRef.current) {
      // console.log(inputRef.current);
      // inputRef.current.setAttribute("aria-expanded", "true");
    }
  }, [promptVal]);

  const handleStatusClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    console.log("stop", pending, isLoading, isValidating);
    e.preventDefault();
    if (pending) {
      // Stop the current request
      console.log("Stopping current request...");
      updateRequest({
        sessionId: id,
        requestId: lastMessages?.[1]?.uid,
        data: { status: "Cancelled", rating: null, review: null },
      })
        .then(() => {
          console.log("Request stopped.");
        })
        .catch((err) => {
          console.error("Error stopping request:", err);
        });
      return;
    }
    if (isValidating || isLoading) {
      // Cancel data fetch via DataContext
      console.log("Cancelling data fetch...");
      cancelDataFetch();
      return;
    }
    if (inputRef.current && inputRef.current.value) {
      handleClick(e as any); // Call the form submit handler
    }
  };

  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const open = Boolean(anchorEl);
  const handleMenuClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorEl(event.currentTarget);
  };
  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  return (
    <Box
      component="form"
      ref={formRef}
      onSubmit={handleClick}
      // tabIndex={-1}
      sx={{
        border: (theme) =>
          hasData
            ? `1px solid ${alpha(theme.palette.text.disabled, 0.2)}`
            : "unset",
        padding: 1.5,
        borderRadius: 6,
      }}
    >
      <Autocomplete
        freeSolo
        openOnFocus
        clearIcon={<ClearIcon fontSize="small" />}
        disableClearable={false}
        // clearOnBlur
        inputValue={promptVal}
        onFocus={(e) => {
          setFocused(true);
        }}
        onBlur={(e) => {
          setFocused(false);
        }}
        onInputChange={(event, newValue, reason) => {
          // console.log("onInputChange", newValue, reason);
          // if (reason !== "reset") {
          setPromptVal(newValue); // keep in sync
          // }
        }}
        // disablePortal
        PopperComponent={StyledPopper}
        slotProps={{
          paper: {
            elevation: 0,
            sx: {
              border: "none",
              backgroundColor: mode === "dark" ? "#1f1e1d" : "#e9e8e6", // dark mode background
            },
          },
        }}
        renderInput={(params) => {
          const { endAdornment } = params.InputProps as any;
          // Try to extract clear and dropdown icons if needed
          const clearButton = endAdornment?.props?.children?.[0];
          // const dropdownIcon = endAdornment?.props?.children?.[1];
          return (
            <Stack direction="column" spacing={1}>
              <TextField
                {...params}
                name="query" // required for form reset
                variant="filled"
                disabled={pending || isLoading || isValidating}
                inputRef={inputRef}
                size="small"
                fullWidth
                multiline
                minRows={1}
                placeholder={placeholder}
                onKeyDown={handleKeyDown}
                value={promptVal}
                onChange={(e) => {
                  setPromptVal(e.target.value);
                }}
                // onChange={handleChange}
                InputProps={{
                  ...params.InputProps,
                  disableUnderline: true,
                  endAdornment: (
                    <Stack direction="row" spacing={1}>
                      {!pending &&
                        !isLoading &&
                        !isValidating &&
                        inputRef.current?.value &&
                        clearButton}
                      {!pending && !isLoading && !isValidating && (
                        <Tooltip title={options[selectedAction]?.label}>
                          <IconButton
                            size="small"
                            onClick={handleClick}
                            disabled={pending || isLoading || isValidating}
                          >
                            <ArrowUpward fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {(pending || isLoading || isValidating) && (
                        <IconButton
                          size="small"
                          type="submit"
                          onClick={handleStatusClick}
                        >
                          <Stop fontSize="small" />
                        </IconButton>
                      )}
                    </Stack>
                  ),
                }}
                sx={{
                  mt: 0,
                  "& .MuiFilledInput-root": {
                    padding: 2,
                    paddingRight: "16px!important", // remove padding to avoid extra space
                    paddingTop: "16px!important", // Ensure padding is consistent
                    paddingBottom: "16px!important", // Ensure padding is consistent
                    borderRadius: 4,
                    alignItems: "center",
                    ".MuiAutocomplete-hasClearIcon.MuiAutocomplete-inputRoot":
                      {},
                  },
                  // Optional: Placeholder styling
                  "& input::placeholder": {
                    opacity: 1,
                  },
                }}
              />
              {/* metadata &&
                hasData &&
                <Instruments
                  selectedAction={selectedAction}
                  setSelectedAction={setSelectedAction}
                />
                 */}
              {metadata && hasData && (
                <Toolbar
                  disableGutters
                  sx={{
                    maxHeight: "32px",
                    minHeight: "32px!important",
                    height: "32px",
                  }}
                >
                  <IconButton
                    size="small"
                    color={
                      context && context !== "General" ? "primary" : "default"
                    }
                    id="instrument-button"
                    aria-controls={open ? "instrument-menu" : undefined}
                    aria-haspopup="true"
                    aria-expanded={open ? "true" : undefined}
                    onClick={handleMenuClick}
                  >
                    <Tune />
                  </IconButton>
                  <Menu
                    id="instrument-menu"
                    anchorEl={anchorEl}
                    open={open}
                    onClose={handleMenuClose}
                    anchorOrigin={{
                      vertical: "top",
                      horizontal: "center",
                    }}
                    transformOrigin={{
                      vertical: "bottom",
                      horizontal: "center",
                    }}
                    slotProps={{
                      root: {
                        "aria-labelledby": "instrument-button",
                      },
                    }}
                  >
                    {Object.entries(options).map((option) => (
                      <MenuItem
                        key={option[1].label}
                        selected={option[0] === selectedAction}
                        onClick={() => {
                          setSelectedAction(option[0] as keyof typeof options);
                          handleMenuClose();
                        }}
                      >
                        <ListItemIcon>{option[1].icon}</ListItemIcon>
                        <ListItemText
                          color={
                            option[0] === selectedAction ? "primary" : "inherit"
                          }
                        >
                          {enrichedContext(option[1].label, context)}
                        </ListItemText>
                      </MenuItem>
                    ))}
                  </Menu>
                  {context && context !== "General" && (
                    <Divider orientation="vertical" />
                  )}
                  {context && context !== "General" && (
                    <Chip
                      variant="outlined"
                      color="primary"
                      onDelete={() => {
                        onSelectColumn(null);
                        onSelectRow(undefined);
                      }}
                      label={enrichedContext(selectedAction, context)}
                      sx={{ maxWidth: "85%" }}
                    />
                  )}
                </Toolbar>
              )}
            </Stack>
          );
        }}
        options={followUps.map((s: string) => ({ label: s }))}
      />
    </Box>
  );
};
