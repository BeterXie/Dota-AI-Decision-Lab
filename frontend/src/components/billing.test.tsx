import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    price: { id: "pri_series", amount: "499", currency_code: "CNY" },
    payment_methods: { card: "one_time", alipay: "one_time", wechat_pay: "one_time" }
  },
  event_pass: {
    enabled: true,
    key: "event_pass",
    scope_type: "EVENT",
    non_expiring: true,
    price: { id: "pri_event", amount: "4999", currency_code: "CNY" },
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
  expect(screen.getByText("Recommended")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("series-pass-price")).toHaveTextContent("4.99"));
  expect(screen.getByTestId("event-pass-price")).toHaveTextContent("49.99");
  expect(screen.getByRole("button", { name: "Select a BO series" })).toBeEnabled();
});

test("selects a series in the membership page before asking the user to sign in and pay", async () => {
  const upcomingMatch = {
    entity_type: "SERIES",
    identity_status: "RESOLVED",
    phase: "PREMATCH",
    id: "series-row",
    series_id: "ec073b7b-6a24-43ad-9700-0db32e0b3595",
    canonical_event_id: "dba2e091-26f2-42f5-b2d5-fd45c937fec5",
    canonical_map_id: null,
    map_number: null,
    valve_match_id: null,
    best_of: 3,
    scheduled_at: "2026-08-21T10:00:00Z",
    tournament_name: "The International 2026",
    round: "Playoffs",
    raw_status: null,
    provider_observed_at: null,
    team_a: { id: "liquid", name: "Team Liquid" },
    team_b: { id: "spirit", name: "Team Spirit" },
    market: [],
    market_quality: null,
    draft: null,
    live: null
  };
  const matches = [
    upcomingMatch,
    {
      ...upcomingMatch,
      id: "completed-series-row",
      series_id: "f50d0c5c-1f42-43ac-955d-a167f7280ce4",
      canonical_event_id: "410e2363-b14a-49bb-a9fa-6ed950601294",
      phase: "POSTMATCH",
      tournament_name: "Completed Cup",
      team_a: { id: "finished-a", name: "Finished Alpha" },
      team_b: { id: "finished-b", name: "Finished Beta" }
    }
  ];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const payload = path === "/api/matches" ? matches : offers;
    return new Response(JSON.stringify(payload), { status: 200 });
  }));
  const props = renderPage();

  fireEvent.click(await screen.findByRole("button", { name: "Select a BO series" }));
  expect(await screen.findByRole("dialog", { name: "Select a BO series" })).toBeInTheDocument();
  expect(screen.queryByText("Finished Alpha vs Finished Beta")).not.toBeInTheDocument();
  const optionLabel = await screen.findByText("Team Liquid vs Team Spirit");
  fireEvent.click(optionLabel.closest("button") as HTMLButtonElement);
  const payButton = screen.getByRole("button", { name: "Sign in to pay" });
  expect(payButton).toBeEnabled();
  fireEvent.click(payButton);
  expect(props.onLogin).toHaveBeenCalledTimes(1);
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

  expect(await screen.findByText("Paid passes are temporarily unavailable")).toBeInTheDocument();
  expect(screen.getByText("Free Access")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
