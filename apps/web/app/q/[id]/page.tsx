import { Box, Container, Paper, Typography } from "@mui/material";
import type { Metadata } from "next";
import { Suspense } from "react";

import { getQuery } from "@/app/lib/gptAPI";
import { QueryContainer } from "@/app/q/[id]/query-container";

import AppBar from "../app-bar";

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

const getQueryById = async (id: string) => getQuery({ queryId: id });

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;

  try {
    // fetch post information
    const query = (await getQueryById(id)) as any;

    if (!query) {
      return {
        title: "Query Not Found",
        description: "The requested query could not be found.",
      };
    }

    return {
      title: `ApeGPT Query: ${query.summary}`,
      description: query.description,
      openGraph: {
        title: `ApeGPT Query: ${query.summary}`,
        description: query.description,
        url: `/q/${id}`,
        images: [
          {
            url: "/apegpt-logo-mark.svg",
            alt: `ApgGPT logo`,
          },
        ],
      },
    };
  } catch (error) {
    console.error("Error generating metadata for query:", error);
    return {
      title: "Query Not Found",
      description: "The requested query could not be found.",
    };
  }
}

const QueryPage = async ({ params, searchParams }: Props) => {
  const { id } = await params;
  const resolvedSearchParams = await searchParams;
  const query = await getQueryById(id);
  const autoDownload = resolvedSearchParams.download === "true";

  return (
    <Suspense fallback={<div>Loading messages...</div>}>
      <AppBar id={id} />
      {!query ? (
        <Container maxWidth={false}>
          <Box
            sx={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              height: "calc(100vh - 64px)",
            }}
          >
            <Paper
              elevation={0}
              sx={{
                p: 4,
                textAlign: "center",
                maxWidth: "500px",
              }}
            >
              <Typography variant="body1" color="textSecondary">
                The query with ID {id} does not exist or could not be loaded.
              </Typography>
            </Paper>
          </Box>
        </Container>
      ) : (
        <QueryContainer
          key={id}
          id={id}
          query={query}
          autoDownload={autoDownload}
        />
      )}
    </Suspense>
  );
};

export default QueryPage;
