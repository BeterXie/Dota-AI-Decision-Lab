import { expect, test, type Page } from "playwright/test";

const now = "2026-08-18T00:00:00Z";

async function mockAccountSession(
  page: Page,
  user: { email: string | null; display_name?: string | null; avatar_url?: string | null }
) {
  let matchDirectoryRequests = 0;
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/session") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          authenticated: true,
          user: {
            id: "99999999-9999-9999-9999-999999999999",
            email: user.email,
            email_verified_at: user.email ? now : null,
            display_name: user.display_name ?? null,
            avatar_url: user.avatar_url ?? null,
            created_at: "2026-08-01T10:00:00Z"
          },
          entitlements: [],
          grants: [
            {
              entitlement: "ai_decisions",
              scope_type: "SERIES",
              scope_ref: "series-ti",
              campaign_key: null,
              starts_at: now,
              expires_at: "2026-08-25T00:00:00Z"
            }
          ],
          providers: { email: true, google: false, steam: true }
        })
      });
      return;
    }
    if (path === "/api/maps") matchDirectoryRequests += 1;
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  return () => matchDirectoryRequests;
}

test("account center groups identity, membership, notifications and language", async ({ page }) => {
  const matchDirectoryRequests = await mockAccountSession(page, { email: "free@example.com" });
  await page.goto("/account");

  await expect(page.getByRole("heading", { name: "账户", exact: true })).toBeVisible();
  await expect(page.getByText("free@example.com", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("免费", { exact: true })).toBeVisible();
  await expect(page.getByText("赛事 / 单场 Pass", { exact: true })).toBeVisible();
  await expect(page.getByText("未开放", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "中文", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /查看 Pro 与赛事 Pass/ })).toHaveAttribute("href", "/billing");
  expect(matchDirectoryRequests()).toBe(0);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("Steam-only account stays usable without a fabricated email", async ({ page }) => {
  await mockAccountSession(page, { email: null, display_name: "DotaFan" });
  await page.goto("/account");

  await expect(page.getByText("DotaFan", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("尚未绑定邮箱", { exact: true })).toBeVisible();
  await expect(page.getByText(/Steam 登录可以不绑定邮箱/)).toBeVisible();
  await expect(page.getByText(/@localhost|@example\.com/)).toHaveCount(0);
});
