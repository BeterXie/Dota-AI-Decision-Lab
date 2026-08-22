import { expect, test } from "playwright/test";

test("keeps account, language, membership and notifications reachable at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === "/api/auth/session"
      ? {
          enabled: true,
          authenticated: true,
          user: {
            id: "99999999-9999-9999-9999-999999999999",
            email: "fan@example.com",
            email_verified_at: "2026-08-18T00:00:00Z",
            display_name: "Dota Fan",
            avatar_url: null,
            created_at: "2026-08-01T00:00:00Z"
          },
          entitlements: [],
          grants: [],
          providers: { email: true, google: false, steam: true }
        }
      : path === "/api/matches"
        ? []
        : null;
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });

  await page.goto("/");
  const accountButton = page.getByRole("button", { name: "打开个人菜单" });
  const accountButtonBox = await accountButton.boundingBox();
  expect(accountButtonBox).not.toBeNull();
  expect((accountButtonBox?.x ?? 0) + (accountButtonBox?.width ?? 0)).toBeLessThanOrEqual(390);
  await accountButton.click();

  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /个人信息/ })).toHaveAttribute("href", "/account");
  await expect(page.getByRole("menuitem", { name: /通知设置/ })).toHaveAttribute("href", "/notifications");
  await expect(page.getByRole("menuitem", { name: /会员中心/ })).toHaveAttribute("href", "/billing");
  await expect(menu.getByRole("button", { name: "中文", exact: true })).toBeVisible();
  await expect(menu.getByRole("button", { name: "EN", exact: true })).toBeVisible();
  await expect(menu.getByRole("button", { name: "退出登录" })).toBeVisible();

  const menuBox = await menu.boundingBox();
  expect(menuBox).not.toBeNull();
  expect((menuBox?.y ?? 0) + (menuBox?.height ?? 0)).toBeLessThanOrEqual(844);

  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(page.getByRole("button", { name: "打开个人菜单" })).toHaveAttribute("aria-expanded", "false");

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});
