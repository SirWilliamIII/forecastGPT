"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000, // 5 minutes - data is considered fresh
            gcTime: 10 * 60 * 1000, // 10 minutes - keep unused data in cache
            refetchOnWindowFocus: false,
            refetchOnMount: false, // Don't refetch on component mount if data exists
            refetchOnReconnect: true, // Refetch when network reconnects
            retry: 2, // Retry failed requests twice
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
