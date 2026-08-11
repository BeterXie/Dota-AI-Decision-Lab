import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";

const runtime = {
  overall: "ACTION_REQUIRED",
  workers: {},
  dependencies: {
    DATABASE: {
      name: "DATABASE",
      status: "READY",
      message: null,
      updated_at: "2026-08-12T12:00:00Z",
      metadata: {}
    }
  },
  observed_at: "2026-08-12T12:00:00Z"
};

beforeEach(() => {
  Object.defineProperty(window, "WebSocket", { value: undefined, configurable: true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith("/api/maps")
        ? []
        : url.endsWith("/api/jobs/summary")
          ? { by_status: {}, by_type: [], oldest_pending_at: null, recent_failures: [] }
          : runtime;
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders operational empty and readiness states", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );

  expect((await screen.findAllByText("ACTION REQUIRED")).length).toBeGreaterThan(0);
  expect(await screen.findByText("No canonical maps")).toBeInTheDocument();
  expect(screen.getByText("Waiting for canonical map discovery")).toBeInTheDocument();
});
