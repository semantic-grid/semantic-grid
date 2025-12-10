"use client";

import { Code, Menu as MenuIcon, TableRows } from "@mui/icons-material";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import type { AppBarProps } from "@mui/material";
import {
  Alert,
  AppBar,
  Box,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  styled,
  Toolbar,
  Tooltip,
} from "@mui/material";
import { useRouter } from "next/navigation";
import React, { useContext, useRef, useState } from "react";

import {
  addQueryToUserDashboard,
  createRequestFromQuery,
  createSession,
} from "@/app/actions";
import { AppContext } from "@/app/contexts/App";
import { ThemeContext } from "@/app/contexts/Theme";
import { useAppUser } from "@/app/hooks/useAppUser";
import { useUserSessions } from "@/app/hooks/useUserSessions";
import NewChatIcon from "@/app/icons/new-chat.svg";
import ShareQuery from "@/app/icons/share.svg";
import ToggleMode from "@/app/icons/toggle-mode.svg";

interface StyledAppBarProps extends AppBarProps {
  open?: boolean;
}

const StyledAppBar = styled(AppBar, {
  shouldForwardProp: (prop) => prop !== "open",
})<StyledAppBarProps>(({ theme }) => ({
  transition: theme.transitions.create(["margin", "width"], {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  variants: [
    {
      props: ({ open }) => open,
      style: {
        width: `calc(100%)`,
        // marginLeft: `${drawerWidth}px`,
        transition: theme.transitions.create(["margin", "width"], {
          easing: theme.transitions.easing.easeOut,
          duration: theme.transitions.duration.enteringScreen,
        }),
      },
    },
  ],
}));

const ConstantAppBar = styled(AppBar, {
  shouldForwardProp: (prop) => prop !== "open",
})<StyledAppBarProps>(() => ({}));

const ApplicationBar = ({ id }: any) => {
  const router = useRouter();
  const { mode, setMode, isLarge } = useContext(ThemeContext);
  const { user, authUser, error } = useAppUser();
  console.log("app bar user", user);
  const { setNavOpen, tab, setTab } = useContext(AppContext);
  const {
    error: dataError,
    mutate,
    isLoading: sessionsAreLoading,
  } = useUserSessions();

  const [anchorEl, setAnchorEl] = useState(null);
  const openMenu = Boolean(anchorEl);
  const creatingSessionRef = useRef(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleTheme = () => {
    setMode(mode === "dark" ? "light" : "dark");
    if (typeof window !== "undefined") {
      window.localStorage.setItem("theme", mode === "dark" ? "light" : "dark");
    }
  };

  const toggleTab = () => {
    setTab((t) => (t === 0 ? 1 : 0));
  };

  const handleClick = (event: any) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleDrawerOpen = () => {
    setNavOpen((o) => !o);
  };

  const onShareClick = () => {
    if (typeof window !== "undefined") {
      // Use the Share API if available
      if (navigator.share) {
        navigator
          .share({
            url: `${window.location.origin}/q/${id}`,
          })
          .catch((error) => {
            console.error("Error sharing:", error);
          });
      }
    }
  };

  const onNewChat = async () => {
    if (creatingSessionRef.current) {
      console.log("Already creating session, skipping duplicate call");
      return;
    }

    if (user?.sub) {
      creatingSessionRef.current = true;
      try {
        const session = await createSession({
          name: `Analyzing query...`,
          tags: "test",
        });
        await mutate();
        if (session) {
          console.log("new session from query", session.session_id);
          await createRequestFromQuery({
            sessionId: session.session_id,
            queryId: id,
          });
          router.replace(`/grid/${session.session_id}`);
        }
      } catch (e) {
        console.error(e);
      } finally {
        creatingSessionRef.current = false;
      }
    }
  };

  const onAddToUserDashboard = async () => {
    const userDashboardId = await addQueryToUserDashboard({
      queryUid: id,
      itemType: "table",
    });
    router.push(`${userDashboardId}`);
  };

  const AppBar = isLarge ? StyledAppBar : ConstantAppBar;

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{
        zIndex: (theme) => theme.zIndex.drawer + 1,
        // borderBottom: (theme) =>
        // `1px solid ${alpha(theme.palette.text.disabled, 0.2)}`,
      }}
    >
      {error && (
        <Alert severity="error" variant="filled">
          {error.message}
        </Alert>
      )}
      <Toolbar variant="dense">
        <Stack
          direction="row"
          sx={{ flexGrow: 1, alignItems: "center" }}
          spacing={2}
        >
          {/* Mobile: hamburger menu */}
          {!isLarge && (
            <IconButton
              aria-label="open menu"
              edge="start"
              onClick={() => setDrawerOpen(true)}
            >
              <MenuIcon />
            </IconButton>
          )}
          {/* Desktop: show action buttons inline */}
          {isLarge && (
            <>
              <Tooltip title="Start new chat">
                <span>
                  <IconButton
                    disabled={!user}
                    aria-label="new chat"
                    edge="start"
                    onClick={onNewChat}
                  >
                    <Box
                      component={NewChatIcon}
                      sx={{ color: "text.secondary" }}
                    />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="Add to User Dashboard">
                <span>
                  <IconButton
                    aria-label="add to user dashboard"
                    edge="start"
                    onClick={onAddToUserDashboard}
                  >
                    <Box
                      component={PlaylistAddIcon}
                      sx={{ color: "text.secondary" }}
                    />
                  </IconButton>
                </span>
              </Tooltip>
            </>
          )}
        </Stack>
        <Stack direction="row" sx={{ alignItems: "center" }} spacing={1}>
          {isLarge &&
            typeof navigator !== "undefined" &&
            Boolean(navigator.share) && (
              <Tooltip title="Share this query">
                <IconButton
                  onClick={onShareClick}
                  color="inherit"
                  sx={{ color: "text.secondary" }}
                >
                  <Box
                    component={ShareQuery}
                    sx={{ color: "text.secondary" }}
                  />
                </IconButton>
              </Tooltip>
            )}
          <Tooltip title="Toggle table/SQL view">
            <IconButton
              onClick={toggleTab}
              color="inherit"
              sx={{ color: "text.secondary" }}
            >
              {tab === 0 ? <Code /> : <TableRows />}
            </IconButton>
          </Tooltip>
          <Tooltip title="Toggle light/dark mode">
            <IconButton onClick={toggleTheme} color="inherit">
              <Box component={ToggleMode} sx={{ color: "text.secondary" }} />
            </IconButton>
          </Tooltip>
          <Menu
            anchorEl={anchorEl}
            elevation={1}
            open={openMenu}
            onClose={handleClose}
            onClick={handleClose}
            transformOrigin={{ horizontal: "right", vertical: "top" }}
            anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
            sx={{
              "& ul": {
                paddingY: "0px",
              },
              "& .MuiButtonBase-root:last-of-type": {
                borderTop: `1px solid ${"palette.grey[300]"}`,
              },
            }}
          >
            {user && authUser && <MenuItem>Profile</MenuItem>}
            {user && !authUser && <MenuItem>Guest Mode</MenuItem>}
            {user && <Divider />}
            {user && <MenuItem>{user?.email}</MenuItem>}
            {authUser && (
              <MenuItem component="a" href="/api/auth/logout">
                Logout
              </MenuItem>
            )}
            {!authUser && (
              <MenuItem component="a" href="/api/auth/login">
                Login
              </MenuItem>
            )}
          </Menu>
        </Stack>
      </Toolbar>
      {/* Mobile drawer */}
      <Drawer
        anchor="left"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Box sx={{ width: 250, pt: 2 }}>
          <List>
            <ListItem disablePadding>
              <ListItemButton
                disabled={!user}
                onClick={() => {
                  setDrawerOpen(false);
                  onNewChat();
                }}
              >
                <ListItemIcon>
                  <Box
                    component={NewChatIcon}
                    sx={{ color: "text.secondary" }}
                  />
                </ListItemIcon>
                <ListItemText primary="Start New Chat" />
              </ListItemButton>
            </ListItem>
            <ListItem disablePadding>
              <ListItemButton
                onClick={() => {
                  setDrawerOpen(false);
                  onAddToUserDashboard();
                }}
              >
                <ListItemIcon>
                  <PlaylistAddIcon sx={{ color: "text.secondary" }} />
                </ListItemIcon>
                <ListItemText primary="Add to Dashboard" />
              </ListItemButton>
            </ListItem>
            {typeof navigator !== "undefined" && Boolean(navigator.share) && (
              <ListItem disablePadding>
                <ListItemButton
                  onClick={() => {
                    setDrawerOpen(false);
                    onShareClick();
                  }}
                >
                  <ListItemIcon>
                    <Box
                      component={ShareQuery}
                      sx={{ color: "text.secondary" }}
                    />
                  </ListItemIcon>
                  <ListItemText primary="Share Query" />
                </ListItemButton>
              </ListItem>
            )}
          </List>
        </Box>
      </Drawer>
    </AppBar>
  );
};

export default ApplicationBar;
