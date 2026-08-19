import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProductRoot } from "./ProductRoot";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

test("unknown paths stay in the product UI and render its not-found page", async () => {
  window.history.replaceState({}, "", "/obsolete-dashboard");
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

  expect(await screen.findByRole("heading", { name: /Page not found|没有找到这个页面/ })).toBeInTheDocument();
});
