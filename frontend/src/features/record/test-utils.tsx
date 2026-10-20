/** Test wrapper for the Record and Agents components: a query client and the tooltip provider. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { TooltipProvider } from "@/ui";

export function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { hook } = memoryLocation({ path: "/" });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Router hook={hook}>{ui}</Router>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}
