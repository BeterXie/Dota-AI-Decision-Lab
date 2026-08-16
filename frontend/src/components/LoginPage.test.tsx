import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { LoginPage } from "./LoginPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

test("requests a code and signs in without a password", async () => {
  Object.defineProperty(window.navigator, "language", { value: "en-US", configurable: true });
  const onAuthenticated = vi.fn();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/auth/request-code")) {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({ email: "viewer@example.com" });
      return response({ accepted: true, sent: true, retry_after_seconds: 60 }, 202);
    }
    if (url.endsWith("/api/auth/verify-code")) {
      expect(JSON.parse(String(init?.body))).toEqual({
        email: "viewer@example.com",
        code: "123456"
      });
      return response({
        enabled: true,
        authenticated: true,
        user: {
          id: "11111111-1111-1111-1111-111111111111",
          email: "viewer@example.com",
          email_verified_at: "2026-08-16T03:00:00Z",
          created_at: "2026-08-16T03:00:00Z"
        }
      });
    }
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <I18nProvider>
      <LoginPage onAuthenticated={onAuthenticated} />
    </I18nProvider>
  );

  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "viewer@example.com" }
  });
  fireEvent.click(screen.getByRole("button", { name: "Send login code" }));

  expect(await screen.findByText("Check your email")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Login code"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  await vi.waitFor(() => expect(onAuthenticated).toHaveBeenCalledTimes(1));
  expect(onAuthenticated.mock.calls[0][0].user.email).toBe("viewer@example.com");
});

test("shows a generic invalid-code error without exposing account details", async () => {
  Object.defineProperty(window.navigator, "language", { value: "en-US", configurable: true });
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/request-code")) {
      return response({ accepted: true, sent: true, retry_after_seconds: 60 }, 202);
    }
    return response({ detail: "invalid or expired login code" }, 401);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <I18nProvider>
      <LoginPage onAuthenticated={vi.fn()} />
    </I18nProvider>
  );
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "viewer@example.com" }
  });
  fireEvent.click(screen.getByRole("button", { name: "Send login code" }));
  await screen.findByText("Check your email");
  fireEvent.change(screen.getByLabelText("Login code"), { target: { value: "654321" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(
    await screen.findByText("That code is invalid or expired. Request a new code and try again.")
  ).toBeInTheDocument();
});
