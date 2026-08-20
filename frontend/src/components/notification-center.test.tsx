import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { NotificationCenterPage } from "./NotificationCenterPage";

vi.mock("qrcode", () => ({
  default: {
    toDataURL: vi.fn(async () => "data:image/png;base64,qr-preview")
  }
}));

const now = "2026-08-17T00:00:00Z";
const center = {
  required_entitlement: "realtime_notifications",
  event_type: "AI_DECISION",
  bindings: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      channel: "EMAIL",
      label: "pro@example.com",
      status: "ACTIVE",
      verified_at: now,
      destination: { email: "pro@example.com" },
      created_at: now
    }
  ],
  preferences: { EMAIL: true, QQ: true, WECHAT: false },
  recent_deliveries: []
};

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <NotificationCenterPage userEmail="pro@example.com" />
      </I18nProvider>
    </QueryClientProvider>
  );
}

test("renders verified account destinations and creates a short-lived QQ pairing command", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/notifications") {
      return new Response(JSON.stringify(center), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
    if (path === "/api/notifications/pairing/qq") {
      return new Response(
        JSON.stringify({
          channel: "QQ",
          code: "ABCD-1234",
          command: "绑定 ABCD-1234",
          expires_at: "2026-08-17T00:10:00Z",
          share_url: "https://qq.example/invite"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response(JSON.stringify({ detail: "not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" }
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage();
  expect(await screen.findByRole("heading", { name: "Notification Center" })).toBeInTheDocument();
  expect(screen.getAllByText("pro@example.com").length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "Verified email bound" })).toBeDisabled();

  const qqCard = screen.getByRole("heading", { name: "QQ Bot" }).closest("article");
  expect(qqCard).not.toBeNull();
  fireEvent.click(within(qqCard!).getByRole("button", { name: "Generate pairing code" }));
  expect(await within(qqCard!).findByText("绑定 ABCD-1234")).toBeInTheDocument();
  expect(within(qqCard!).getByRole("link", { name: /Open QQ and add bot/i })).toHaveAttribute(
    "href",
    "https://qq.example/invite"
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/notifications/pairing/qq",
    expect.objectContaining({ method: "POST", credentials: "same-origin" })
  );
});

test("renders a QR image for a user-owned QQ binding session", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/notifications") {
      return new Response(JSON.stringify(center), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
    if (path === "/api/notifications/qr/qq/start") {
      return new Response(JSON.stringify({
        channel: "QQ",
        session_id: "qr-session",
        status: "WAITING",
        qrcode_url: "https://q.qq.com/qqbot/openclaw/connect.html?task_id=task",
        created_at: now,
        expires_at: "2026-08-17T00:05:00Z"
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
    return new Response(JSON.stringify({ detail: "not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" }
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage();
  await screen.findByRole("heading", { name: "Notification Center" });
  const qqCard = screen.getByRole("heading", { name: "QQ Bot" }).closest("article");
  expect(qqCard).not.toBeNull();
  fireEvent.click(within(qqCard!).getByRole("button", { name: "Scan to bind your account" }));
  const image = await within(qqCard!).findByAltText("Scan to bind account");
  expect(image).toHaveAttribute("src", "data:image/png;base64,qr-preview");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/notifications/qr/qq/start",
    expect.objectContaining({ method: "POST", credentials: "same-origin" })
  );
});
