import { Container, Paper, Typography } from "@mui/material";
import React from "react";

import { ensureSession } from "@/app/actions";
import GridNavClient from "@/app/components/GridNavClient";
import { getDashboards } from "@/app/lib/payload";

const HomePage = async () => {
  const { uid, dashboardId } = await ensureSession();
  const dashboards = await getDashboards(uid ?? undefined);

  return (
    <>
      <GridNavClient
        dashboards={dashboards}
        uid={uid ?? undefined}
        dashboardId={dashboardId ?? undefined}
      />
      <Container
        maxWidth={false}
        sx={{
          width: "100%",
          height: "calc(100vh)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Paper elevation={0}>
          <Typography variant="overline">Loading...</Typography>
        </Paper>
      </Container>
    </>
  );
};

export default HomePage;
