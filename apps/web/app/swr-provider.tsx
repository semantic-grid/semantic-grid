"use client";

import { SWRConfig } from "swr";

import { localStorageProvider } from "@/app/contexts/localStorageProvider";
import { defaultSWRConfig, parseErrorMessage } from "@/app/lib/swrConfig";

const SWRProvider = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig
    value={{
      provider: () => localStorageProvider() as any,
      ...defaultSWRConfig,
      // Custom error handler with user-friendly messages
      onError: (error, key) => {
        const message = parseErrorMessage(error);
        // eslint-disable-next-line no-console
        console.error(`[SWR Error] ${key}:`, message, error);

        // Show user-friendly toast for critical errors
        if (
          error?.status === 503 ||
          error?.message?.includes("Circuit breaker")
        ) {
          // You can integrate with a toast library here if needed
          // eslint-disable-next-line no-console
          console.warn(`[User Message] ${message}`);
        }
      },
    }}
  >
    {children}
  </SWRConfig>
);

export default SWRProvider;
