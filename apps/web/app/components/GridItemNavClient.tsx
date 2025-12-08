"use client";

import MenuIcon from "@mui/icons-material/Menu";
import {
  alpha,
  AppBar,
  Box,
  Button,
  Container,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Toolbar,
} from "@mui/material";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { useContext, useEffect, useState } from "react";

import { addQueryToUserDashboard } from "@/app/actions";
import { ItemViewSwitcher } from "@/app/components/ItemViewSwitcher";
import { SemanticGridMenu } from "@/app/components/SemanticGridMenu";
import { UserProfileMenu } from "@/app/components/UserProfileMenu";
import { AppContext } from "@/app/contexts/App";
import { useItemViewContext } from "@/app/contexts/ItemView";
import { ThemeContext } from "@/app/contexts/Theme";

type Dashboard = {
  id: string;
  name: string;
  slug: string;
};

const GridItemNavClient = ({
  id,
  dashboards,
  uid,
  dashboardId,
  metadata,
  queryUid,
  lastMessage,
}: {
  id: string;
  dashboards: Dashboard[];
  uid?: string;
  dashboardId?: string;
  metadata?: any;
  queryUid?: string;
  lastMessage?: any;
}) => {
  const router = useRouter();
  const pathname = usePathname();
  const { isLarge } = useContext(ThemeContext);
  const { setNavOpen, editMode, setEditMode } = useContext(AppContext);
  const { view } = useItemViewContext();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleToggle = () => {
    if (editMode && queryUid) {
      addQueryToUserDashboard({
        queryUid,
        itemType: view === "chart" ? "chart" : "table",
        name: metadata?.summary || metadata?.intent,
      }).then(() => {
        setEditMode("");
        router.replace(`/user/${uid}`);
      });
    } else {
      setEditMode("");
      router.replace(editMode);
    }
  };

  useEffect(() => {
    if (!editMode) {
      setEditMode("/");
    }
  }, []);

  return (
    <>
      {/* Mobile navigation drawer */}
      <Drawer
        anchor="left"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Box sx={{ width: 250, pt: 2 }}>
          <List>
            {dashboards.map((d) => (
              <ListItem key={d.id} disablePadding>
                <ListItemButton
                  component={Link}
                  href={d.slug}
                  selected={pathname === d.slug}
                  onClick={() => setDrawerOpen(false)}
                >
                  <ListItemText primary={d.name} />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        </Box>
      </Drawer>

      {/* App bar */}
      <AppBar
        position="relative"
        elevation={0}
        enableColorOnDark
        sx={{
          bgcolor: alpha("#EF8626", 0.2),
          color: (theme) => theme.palette.text.primary,
        }}
      >
        <Container maxWidth={false}>
          <Toolbar disableGutters sx={{ gap: 2 }}>
            {/* Mobile menu button */}
            {!isLarge && (
              <IconButton
                edge="start"
                color="inherit"
                aria-label="menu"
                onClick={() => setDrawerOpen(true)}
              >
                <MenuIcon />
              </IconButton>
            )}

            {/* Desktop dashboard navigation */}
            {isLarge &&
              dashboards.map((d) => (
                <Button
                  key={d.id}
                  component={Link}
                  href={d.slug}
                  variant="text"
                  color={pathname === d.slug ? "primary" : "inherit"}
                  sx={{
                    textTransform: "none",
                    "&.MuiButtonBase-root.MuiButton-root": {
                      fontSize: "1.1rem",
                      fontWeight: 900,
                    },
                  }}
                >
                  {d.name}
                </Button>
              ))}

            {/* Spacer between primary nav and right-side controls */}
            <Box sx={{ flexGrow: 1 }} />

            {/* Hide view switcher on mobile - tabs already provide this */}
            {isLarge && <ItemViewSwitcher />}

            <SemanticGridMenu
              mode="editing"
              onActionClick={handleToggle}
              hasQuery={Boolean(metadata)}
            />

            <UserProfileMenu />
          </Toolbar>
        </Container>
      </AppBar>
    </>
  );
};

export default GridItemNavClient;
