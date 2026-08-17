import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { BillingPage } from "./BillingPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage(props?: Partial<React.ComponentProps<typeof BillingPage>>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const defaults = { authenticated: false, hasPro: false, onLogin: vi.fn() };
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
  offers: [
    {
      key: "pro_monthly",
      label: "Pro Monthly",
      kind: "subscription",
      grant_days: null,
      entitlements: ["ai_decisions", "realtime_notifications"],
      payment_methods: {
        card: "subscription",
        alipay: "subscription",
        wechat_pay: "not_supported_for_subscription"
      }
    },
    {
      key: "pro_30d",
      label: "Pro 30-day Pass",
      kind: "fixed_term",
      grant_days: 30,
      entitlements: ["ai_decisions", "realtime_notifications"],
      payment_methods: { card: "one_time", alipay: "one_time", wechat_pay: "one_time" }
    }
  ],
  local_payment_notes: { alipay: "eligible", wechat_pay: "one time" },
  crypto: { enabled: false, architecture: "separate_provider_adapter", status: "disabled_by_default" }
};

test("shows WeChat Pay only on fixed-term offers and asks anonymous users to sign in", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(offers), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  })));
  const props = renderPage();

  const monthly = (await screen.findByText("Pro Monthly")).closest("article");
  const pass = screen.getByText("Pro 30-day Pass").closest("article");
  expect(monthly).not.toBeNull();
  expect(pass).not.toBeNull();
  expect(within(monthly!).getByText("WeChat Pay · —")).toBeInTheDocument();
  expect(within(pass!).getByText("WeChat Pay · One-time")).toBeInTheDocument();

  fireEvent.click(within(pass!).getByRole("button", { name: "Sign in to buy" }));
  expect(props.onLogin).toHaveBeenCalledTimes(1);
});

test("does not call checkout while Paddle is disabled", async () => {
  const disabled = { ...offers, enabled: false, offers: [] };
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(disabled), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  }));
  vi.stubGlobal("fetch", fetchMock);
  renderPage({ authenticated: true });

  expect(await screen.findByText("Paddle is not enabled yet")).toBeInTheDocument();
  expect(screen.queryByText("Continue to secure checkout")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
