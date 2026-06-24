"use client";
import { QueryClient, QueryClientProvider, QueryCache } from "@tanstack/react-query";
import toast, { Toaster } from "react-hot-toast";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        // Surface data-fetch failures globally so a failed request is visibly
        // distinct from genuinely-empty data (otherwise both render the same
        // empty state and the user can't tell the difference). 401s are handled
        // by the axios interceptor (token refresh / redirect), so skip those.
        queryCache: new QueryCache({
          onError: (error, query) => {
            const status = (error as { response?: { status?: number } })?.response?.status;
            if (status === 401) return;
            const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            toast.error(detail || "Couldn't load data — check your connection and retry.", {
              id: `qerr-${String(query.queryHash)}`, // dedupe repeated failures of the same query
            });
          },
        }),
        defaultOptions: {
          queries: { retry: 1, staleTime: 30_000 },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "hsl(224 71% 6%)",
            color: "hsl(213 31% 91%)",
            border: "1px solid hsl(216 34% 17%)",
          },
        }}
      />
    </QueryClientProvider>
  );
}
