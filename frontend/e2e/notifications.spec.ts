import { expect, test, type Page } from "playwright/test";

const now = "2026-08-17T00:00:00Z";
const user = {
  id: "99999999-9999-9999-9999-999999999999",
  email: "pro@example.com",
  email_verified_at: now,
  created_at: now
};

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
  preferences: { EMAIL: true, QQ: true, WECHAT: true },
  recent_deliveries: []
};

async function mockNotificationApi(page: Page, { entitled }: { entitled: boolean }) {
  let notificationRequests = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let payload: unknown = null;
    if (path === "/api/auth/session") {
      payload = {
        enabled: true,
        authenticated: true,
        user,
        entitlements: entitled ? ["ai_decisions", "realtime_notifications"] : ["ai_decisions"]
      };
    } else if (path === "/api/notifications") {
      notificationRequests += 1;
      payload = center;
    } else if (path === "/api/notifications/pairing/qq") {
      notificationRequests += 1;
      payload = {
        channel: "QQ",
        code: "ABCD-1234",
        command: "绑定 ABCD-1234",
        expires_at: "2026-08-17T00:10:00Z"
      };
    }
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });
  return () => notificationRequests;
}

test("keeps Notification Center locked for signed-in users without realtime entitlement", async ({ page }) => {
  const notificationRequests = await mockNotificationApi(page, { entitled: false });
  await page.goto("/notifications?e2e=free-notifications");

  await expect(
    page.getByRole("heading", { name: "Realtime Notification Center is a Pro feature" })
  ).toBeVisible();
  await expect(
    page.getByText("This account does not have realtime_notifications access yet.")
  ).toBeVisible();
  expect(notificationRequests()).toBe(0);
});

test("lets an entitled user manage channels and generate a verified QQ pairing command", async ({ page }) => {
  await mockNotificationApi(page, { entitled: true });
  await page.goto("/notifications?e2e=pro-notifications");

  await expect(page.getByRole("heading", { name: "Notification Center" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Email" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "QQ Bot" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "WeChat Bot" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verified email bound" })).toBeDisabled();

  const qqCard = page
    .locator("article")
    .filter({ has: page.getByRole("heading", { name: "QQ Bot" }) });
  await qqCard.getByRole("button", { name: "Generate pairing code" }).click();
  await expect(qqCard.getByText("绑定 ABCD-1234")).toBeVisible();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});
