import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { TopBar } from "./TopBar";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderTopBar({
  authEnabled = true,
  authenticated = false,
  onLogin = vi.fn()
}: {
  authEnabled?: boolean;
  authenticated?: boolean;
  onLogin?: () => void;
} = {}) {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "en");
  render(
    <I18nProvider>
      <TopBar
        runtime={undefined}
        onOpenDiagnostics={() => undefined}
        onRefresh={() => undefined}
        authEnabled={authEnabled}
        authenticated={authenticated}
        onLogin={onLogin}
      />
    </I18nProvider>
  );
  return onLogin;
}

test("top bar exposes the real login action and Pro billing route", () => {
  const onLogin = vi.fn();
  renderTopBar({ onLogin });

  expect(screen.getByRole("link", { name: /Get Pro/ })).toHaveAttribute("href", "/billing");
  fireEvent.click(screen.getByRole("button", { name: "Log in" }));
  expect(onLogin).toHaveBeenCalledTimes(1);
});

test("top bar makes disabled authentication visible instead of hiding the entry", () => {
  renderTopBar({ authEnabled: false });

  expect(screen.getByRole("button", { name: "Login off" })).toBeDisabled();
  expect(screen.getByRole("link", { name: /Get Pro/ })).toHaveAttribute("href", "/billing");
});

test("signed-in users get an account entry while billing remains discoverable", () => {
  renderTopBar({ authenticated: true });

  expect(screen.getByRole("link", { name: "Account" })).toHaveAttribute("href", "/billing");
  expect(screen.queryByRole("button", { name: "Log in" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Get Pro/ })).toHaveAttribute("href", "/billing");
});
