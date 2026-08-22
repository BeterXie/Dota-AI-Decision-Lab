import { expect, test, type Page } from "playwright/test";

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
    series_id: "ti15-series-b",
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

async function mockHomeApi(page: Page, matchPayload = matches) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === "/api/auth/session" ? anonymousSession : path === "/api/matches" ? matchPayload : null;
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  });
});

test("2.0 homepage explains the product and surfaces live, upcoming and completed matches", async ({ page }) => {
  await mockHomeApi(page);
  await page.goto("/");

  await expect(page).toHaveTitle("DotaScope");
  await expect(page.getByRole("link", { name: "DotaScope" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "看懂比赛，验证 AI，追踪真实表现" })).toBeVisible();
  if ((page.viewportSize()?.width ?? 0) <= 760) {
    await page.getByRole("button", { name: "打开主导航" }).click();
  }
  await expect(page.getByRole("link", { name: "首页" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("正在进行与即将开始", { exact: true })).toBeVisible();
  await expect(page.getByText("The International 2026", { exact: true })).toBeVisible();
  await expect(page.getByText("Team Spirit")).toBeVisible();
  await expect(page.getByText("Tundra Esports")).toBeVisible();
  await expect(page.getByText("比赛追踪", { exact: true })).toBeVisible();
  await expect(page.getByText("AI 预测对比", { exact: true })).toBeVisible();
  await expect(page.getByText("Shadow 表现复盘", { exact: true })).toBeVisible();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("does not present completed events as current when no live or upcoming event exists", async ({ page }) => {
  await mockHomeApi(page, [matches[2]]);
  await page.goto("/");

  await expect(page.getByText("正在进行与即将开始", { exact: true })).toBeVisible();
  await expect(
    page.getByText("目前没有进行中或即将开始的赛事。历史赛事仍可在全部赛事中查看。", { exact: true })
  ).toBeVisible();
  await expect(page.locator("#current-events").getByText("DreamLeague S24", { exact: true })).toHaveCount(0);
  await expect(page.getByText("DreamLeague S24", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Tundra Esports")).toBeVisible();
});

test("avatar opens the unified login dialog and does not fake unconfigured social providers", async ({ page }) => {
  await mockHomeApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "登录", exact: true }).click();

  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("heading", { name: "登录 DotaScope" })).toBeVisible();
  await expect(page.getByRole("button", { name: /使用 Google 账号继续/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /使用 Steam 登录/ })).toBeDisabled();
  await expect(page.getByLabel("邮箱")).toBeVisible();
  await expect(page.getByRole("button", { name: "发送验证码" })).toBeDisabled();
});
