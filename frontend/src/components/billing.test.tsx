import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { BillingPage } from "./BillingPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage(props?: Partial<React.ComponentProps<typeof BillingPage>>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const defaults = { authenticated: false, onLogin: vi.fn() };
  const merged = { ...defaults, ...props };
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <BillingPage {...merged} />
      </I18nProvider>
    </QueryClientProvider>
  );
  return merged;
}

const offers = {
  provider: "paddle",
  enabled: true,
  environment: "sandbox",
  series_pass: {
    enabled: true,
    key: "series_pass",
    scope_type: "SERIES",
    non_expiring: true,
    payment_methods: { card: "one_time", alipay: "one_time", wechat_pay: "one_time" }
  },
  event_pass: {
    enabled: true,
    key: "event_pass",
    scope_type: "EVENT",
    non_expiring: true,
    payment_methods: { card: "one_time", alipay: "one_time", wechat_pay: "one_time" }
  },
  referral: { enabled: false, campaign_key: "referral-v1" },
  local_payment_notes: { alipay: "eligible", wechat_pay: "one time" },
  crypto: { enabled: false, architecture: "separate_provider_adapter", status: "disabled_by_default" }
};

const account = { entitlements: [], grants: [], passes: [] };

test("shows Free, Series Pass and Event Pass tiers", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(offers), { status: 200 }))
  );
  renderPage();

  expect(await screen.findByText("Free Access")).toBeInTheDocument();
  expect(screen.getAllByText("Series Pass").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Event Pass").length).toBeGreaterThan(0);
});

test("does not call checkout while Paddle is disabled", async () => {
  const disabled = { ...offers, enabled: false, series_pass: { enabled: false }, event_pass: { enabled: false } };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const payload = path === "/api/billing/account" ? account : disabled;
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage({ authenticated: true });

  expect(await screen.findByText("Paddle is not enabled yet")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
