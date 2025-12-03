import "@/app/globals.css";

import { UserProvider } from "@auth0/nextjs-auth0/client";
import { CssBaseline } from "@mui/material";
import { AppRouterCacheProvider } from "@mui/material-nextjs/v13-appRouter";
import Script from "next/script";
import React from "react";

import ApiErrorHandler from "@/app/components/ApiErrorHandler";
import GlobalErrorHandler from "@/app/components/GlobalErrorHandler";
import MuiXLicense from "@/app/components/MuiLicense";
import { AppProvider } from "@/app/contexts/App";
import { DataProvider } from "@/app/contexts/DataContext";
import { DataFetchProvider } from "@/app/contexts/DataFetchContext";
import { FlexibleThemeProvider } from "@/app/contexts/Theme";
import SWRProvider from "@/app/swr-provider";

export const dynamic = "force-dynamic";

const RootLayout = ({ children }: { children: React.ReactElement }) => (
  <html lang="en">
    <head>
      {process.env.NEXT_PUBLIC_GOOGLE_ANALYTICS && (
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${process.env.NEXT_PUBLIC_GOOGLE_ANALYTICS}`}
          strategy="afterInteractive"
        />
      )}
      <Script id="google-analytics" strategy="afterInteractive">
        {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', '${process.env.NEXT_PUBLIC_GOOGLE_ANALYTICS}', {
              page_path: window.location.pathname,
            });
          `}
      </Script>
    </head>
    <body>
      <AppRouterCacheProvider>
        <CssBaseline />
        <FlexibleThemeProvider>
          <UserProvider>
            <SWRProvider>
              <DataProvider>
                <DataFetchProvider>
                  <AppProvider>
                    {children}
                    <MuiXLicense />
                    <ApiErrorHandler />
                    <GlobalErrorHandler />
                  </AppProvider>
                </DataFetchProvider>
              </DataProvider>
            </SWRProvider>
          </UserProvider>
        </FlexibleThemeProvider>
      </AppRouterCacheProvider>
    </body>
  </html>
);

export default RootLayout;
