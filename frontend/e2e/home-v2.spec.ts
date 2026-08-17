import { expect, test } from "playwright/test";

const now = "2026-08-18T08:00:00Z";

const anonymousSession = {
  enabled: true,
  authenticated: false,
  user: null,
  entitlements: [],
  grants: [],
  providers: { email: true, google: false, steam: false }
};

const matches = [
  {
    id: "live-map",
    series_id: "ti15-series",
    canonical_map_id: "live-map",
    phase: "LIVE",
    scheduled_at: "2026-08-18T09:00:00Z",
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    team_a: { id: "liquid", name: "Team Liquid" },
    team_b: { id: "yandex", name: "Team Yandex" },
    best_of: 3,
    series_score: { team_a: 1, team_b: 1 }
  },
  {
    id: "upcoming-map",
    series_id: "ti15-series",
    canonical_map_id: "upcoming-map",
    phase: "PREMATCH",
    scheduled_at: "2026-08-18T12:00:00Z",
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    team_a: { id: "spirit", name: "Team Spirit" },
    team_b: { id: "falcons", name: "Team Falcons" },
    best_of: 3,
    series_score: { team_a: 0, team_b: 0 }
  },
  {
    id: "completed-map",
    series_id: "dreamleague-series",
    canonical_map_id: "completed-map",
    phase: "POSTMATCH",
    scheduled_at: "2026-08-17T18:00:00Z",
    tournament_name: "DreamLeague S24",
    round: "淘汰赛",
    team_a: { id: "tundra", name: "Tundra Esports" },
    team_b: { id: "betboom", name: "BetBoom Team" },
    best_of: 3,
    series_score: { team_a: 2, team_b: 0 }
  }
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === "/api/auth/session" ? anonymousSession : path === "/api/matches" ? matches : null;
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });
});

test("2.0 homepage explains the product and surfaces live, upcoming and completed matches", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "看懂比赛，验证 AI，追踪真实表现" })).toBeVisible();
  await expect(page.getByRole("link", { name: "首页" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("正在进行的赛事", { exact: true })).toBeVisible();
  await expect(page.getByText("TI15 国际邀请赛", { exact: true })).toBeVisible();
  await expect(page.getByText("Team Spirit")).toBeVisible();
  await expect(page.getByText("Tundra Esports")).toBeVisible();
  await expect(page.getByText("比赛追踪", { exact: true })).toBeVisible();
  await expect(page.getByText("AI 决策对比", { exact: true })).toBeVisible();
  await expect(page.getByText("Shadow 表现复盘", { exact: true })).toBeVisible();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("avatar opens the unified login dialog and does not fake unconfigured social providers", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "登录", exact: true }).click();

  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("heading", { name: "登录 Dota AI Decision Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: /使用 Google 账号继续/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /使用 Steam 登录/ })).toBeDisabled();
  await expect(page.getByLabel("邮箱")).toBeVisible();
  await expect(page.getByRole("button", { name: "发送验证码" })).toBeDisabled();
});
