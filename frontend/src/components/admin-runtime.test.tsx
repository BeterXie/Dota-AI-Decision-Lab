import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AuthSessionState } from "../authApi";
import { I18nProvider } from "../i18n";
import { AdminRuntimePage } from "./AdminRuntimePage";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

test("does not offer a dead sign-in action when global auth is disabled", () => {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  const session: AuthSessionState = {
    enabled: false,
    authenticated: true,
    user: null,
    entitlements: [],
    grants: []
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AdminRuntimePage
          pathname="/admin/runtime"
          session={session}
          authLoading={false}
          onLogin={vi.fn()}
          onLogout={vi.fn().mockResolvedValue(undefined)}
        />
      </I18nProvider>
    </QueryClientProvider>
  );

  expect(screen.getByRole("heading", { name: "认证服务未启用" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
});
