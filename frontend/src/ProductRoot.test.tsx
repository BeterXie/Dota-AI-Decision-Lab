import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProductRoot } from "./ProductRoot";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

function renderProductAt(pathname: string) {
  window.history.replaceState({}, "", pathname);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    enabled: true,
    authenticated: false,
    user: null,
    entitlements: [],
    grants: [],
    providers: { email: true, google: false, steam: false }
  }), { status: 200, headers: { "Content-Type": "application/json" } })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<QueryClientProvider client={client}><ProductRoot /></QueryClientProvider>);
}

test("unknown paths stay in the product UI and render its not-found page", async () => {
  renderProductAt("/obsolete-dashboard");

  expect(await screen.findByRole("heading", { name: /Page not found|没有找到这个页面/ })).toBeInTheDocument();
});

test("renders Terms of Use with persistent footer legal links", async () => {
  renderProductAt("/terms");

  expect(await screen.findByRole("heading", { name: /Terms of Use|使用条款/ })).toBeInTheDocument();
  expect(screen.getByText(/Points have no cash value|积分没有现金价值/)).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: /Terms of Use|使用条款/ }).length).toBeGreaterThan(0);
  expect(screen.getAllByRole("link", { name: /Privacy Policy|隐私政策/ }).length).toBeGreaterThan(0);
});

test("renders the Privacy Policy through the product route", async () => {
  renderProductAt("/privacy");

  expect(await screen.findByRole("heading", { name: /Privacy Policy|隐私政策/ })).toBeInTheDocument();
  expect(screen.getByText(/Paddle handles payment details|支付信息由 Paddle 处理/)).toBeInTheDocument();
});
