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

import { SemanticGridMenu } from "@/app/components/SemanticGridMenu";
import { UserProfileMenu } from "@/app/components/UserProfileMenu";
import { AppContext } from "@/app/contexts/App";
import { ThemeContext } from "@/app/contexts/Theme";

type Dashboard = {
  id: string;
  name: string;
  slug: string;
};

const TopNavClient = ({ dashboards }: { dashboards: Dashboard[] }) => {
  const router = useRouter();
  const pathname = usePathname();
  const { isLarge } = useContext(ThemeContext);
  const { editMode, setEditMode } = useContext(AppContext);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleToggle = () => {
    if (!editMode) {
      router.push(`/grid`);
      setEditMode(pathname);
    }
  };

  useEffect(() => {
    if (editMode) {
      setEditMode("");
    }
  }, [pathname, editMode]);

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
          bgcolor: (theme) => alpha(theme.palette.divider, 0.05),
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

            <SemanticGridMenu mode="explore" onActionClick={handleToggle} />

            <UserProfileMenu />
          </Toolbar>
        </Container>
      </AppBar>
    </>
  );
};

export default TopNavClient;
