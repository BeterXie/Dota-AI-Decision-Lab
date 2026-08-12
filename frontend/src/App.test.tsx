import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  window.localStorage.clear();
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
  cleanup();
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

test("switches to Chinese and restores the choice after remount", async () => {
  const firstClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const firstView = render(
    <QueryClientProvider client={firstClient}>
      <App />
    </QueryClientProvider>
  );

  fireEvent.click(await screen.findByRole("button", { name: "中文" }));
  expect(await screen.findByText("暂无规范化地图")).toBeInTheDocument();
  expect(screen.getByText("等待规范化地图发现")).toBeInTheDocument();
  expect(window.localStorage.getItem("dota-ai-decision-lab-locale")).toBe("zh-CN");
  expect(document.documentElement.lang).toBe("zh-CN");

  firstView.unmount();
  const secondClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={secondClient}>
      <App />
    </QueryClientProvider>
  );

  expect(await screen.findByText("暂无规范化地图")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
});
