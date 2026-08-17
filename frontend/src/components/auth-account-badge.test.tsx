import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { AuthAccountBadge } from "./AuthAccountBadge";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

const user = {
  id: "99999999-9999-9999-9999-999999999999",
  email: "dev@localhost",
  email_verified_at: "2026-08-18T00:00:00Z",
  created_at: "2026-08-18T00:00:00Z"
};

test("bottom account badge surfaces logout failures and allows retry", async () => {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  const onLogout = vi.fn().mockRejectedValue(new Error("logout failed"));

  render(
    <I18nProvider>
      <AuthAccountBadge user={user} onLogout={onLogout} />
    </I18nProvider>
  );

  const button = screen.getByRole("button", { name: "退出" });
  fireEvent.click(button);

  expect(onLogout).toHaveBeenCalledTimes(1);
  expect(await screen.findByRole("alert")).toHaveTextContent("退出失败，请重试");
  await waitFor(() => expect(button).not.toBeDisabled());
});
