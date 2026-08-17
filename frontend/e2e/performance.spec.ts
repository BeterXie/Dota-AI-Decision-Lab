import { expect, test, type Page } from "playwright/test";

const gptIdentity = {
  provider: "openai",
  model: "gpt-5.6",
  prompt_version: "decision-analyst-v5.1-output",
  decision_policy_version: "shadow-tournament-portfolio-v3",
  ai_view_version: "ai-view-v6"
};
const deepseekIdentity = {
  ...gptIdentity,
  provider: "deepseek",
  model: "deepseek-reasoner"
};

const leaderboard = {
  scope: "ALL_CANONICAL_EVENTS",
  ranking: "REALIZED_ROI_THEN_PNL",
  experiments: [
    {
      rank: 1,
      experiment: gptIdentity,
      event_count: 2,
      total_initial_bankroll: 20000,
      cash_balance: 22600,
      locked_balance: 0,
      equity: 22600,
      realized_pnl: 2600,
      realized_roi: 0.13,
      profitable_events: 2,
      losing_events: 0,
      flat_events: 0,
      profitable_event_rate: 1,
      bankrupt_events: 0,
      worst_event_drawdown_pct: 0.09,
      bet_count: 12,
      open_bet_count: 0,
      rejected_bet_count: 1,
      wins: 8,
      losses: 4,
      hit_rate: 8 / 12,
      turnover: 7200,
      profit_factor: 1.9,
      events: [
        {
          canonical_event_id: "event-dreamleague",
          event_name: "DreamLeague",
          started_at: "2026-07-10T10:00:00Z",
          ended_at: "2026-07-15T18:00:00Z",
          initial_bankroll: 10000,
          equity: 10800,
          realized_pnl: 800,
          realized_roi: 0.08,
          max_drawdown_pct: 0.09,
          status: "ACTIVE"
        },
        {
          canonical_event_id: "event-ti",
          event_name: "The International",
          started_at: "2026-08-10T10:00:00Z",
          ended_at: "2026-08-17T18:00:00Z",
          initial_bankroll: 10000,
          equity: 11800,
          realized_pnl: 1800,
          realized_roi: 0.18,
          max_drawdown_pct: 0.07,
          status: "ACTIVE"
        }
      ]
    },
    {
      rank: 2,
      experiment: deepseekIdentity,
      event_count: 1,
      total_initial_bankroll: 10000,
      cash_balance: 9600,
      locked_balance: 0,
      equity: 9600,
      realized_pnl: -400,
      realized_roi: -0.04,
      profitable_events: 0,
      losing_events: 1,
      flat_events: 0,
      profitable_event_rate: 0,
      bankrupt_events: 0,
      worst_event_drawdown_pct: 0.16,
      bet_count: 7,
      open_bet_count: 0,
      rejected_bet_count: 2,
      wins: 3,
      losses: 4,
      hit_rate: 3 / 7,
      turnover: 4600,
      profit_factor: 0.82,
      events: [
        {
          canonical_event_id: "event-ti",
          event_name: "The International",
          started_at: "2026-08-10T10:00:00Z",
          ended_at: "2026-08-17T18:00:00Z",
          initial_bankroll: 10000,
          equity: 9600,
          realized_pnl: -400,
          realized_roi: -0.04,
          max_drawdown_pct: 0.16,
          status: "ACTIVE"
        }
      ]
    }
  ]
};

function eventExperiment(identity: typeof gptIdentity, accountId: string, pnl: number) {
  return {
    experiment: identity,
    portfolio: {
      account_id: accountId,
      canonical_event_id: "event-ti",
      experiment: identity,
      initial_bankroll: 10000,
      cash_balance: 10000 + pnl,
      locked_balance: 0,
      equity: 10000 + pnl,
      realized_pnl: pnl,
      roi: pnl / 10000,
      peak_equity: 12100,
      max_drawdown: 650,
      max_drawdown_pct: identity.provider === "openai" ? 0.07 : 0.16,
      bet_count: 7,
      open_bet_count: 0,
      rejected_bet_count: 1,
      wins: 5,
      losses: 2,
      hit_rate: 5 / 7,
      turnover: 4300,
      profit_factor: 1.8,
      status: "ACTIVE"
    },
    quality: {
      sample_policy: {
        prediction: "FIRST_EVALUABLE_FORECAST_PER_MAP",
        clv: "FIRST_SETTLED_POSITION_PER_MAP",
        portfolio: "ALL_EXECUTED_POSITIONS"
      },
      settled_maps: 24,
      successful_decisions: 46,
      action_counts: { BUY_A: 8, BUY_B: 6, NO_BUY: 32 },
      prediction_sample_count: 22,
      average_brier_score: 0.18,
      average_log_loss: 0.51,
      average_clv: 0.025,
      clv_sample_count: 12,
      market_comparison: {
        sample_count: 21,
        market_average_brier_score: 0.205,
        ai_average_brier_score: 0.18,
        brier_improvement_vs_market: 0.025,
        market_average_log_loss: 0.56,
        ai_average_log_loss: 0.51,
        log_loss_improvement_vs_market: 0.05
      },
      decision_level: {
        prediction_sample_count: 40,
        average_brier_score: 0.19,
        average_log_loss: 0.53,
        average_clv: 0.018,
        clv_sample_count: 18
      },
      average_stake_pct_of_available_cash: 0.075,
      largest_stake_pct_of_available_cash: 0.14,
      longest_losing_streak: 2,
      risk_adjusted_return_over_max_drawdown: 2.5
    },
    execution_latency: {
      source: "DECISION_FUTURE_ODDS_TIME_HORIZON",
      position_policy: "FIRST_SETTLED_POSITION_PER_MAP",
      interpretation: "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",
      pre_response_capture_count: 1,
      invalid_pair_capture_count: 0,
      horizons: {
        "30": {
          sample_count: 9,
          actionable_count: 6,
          actionable_rate: 2 / 3,
          average_model_edge_vs_break_even: 0.038,
          average_odds_slippage_pct: -0.012,
          average_observed_after_ai_seconds: 31.2
        },
        "60": {
          sample_count: 8,
          actionable_count: 4,
          actionable_rate: 0.5,
          average_model_edge_vs_break_even: 0.021,
          average_odds_slippage_pct: -0.027,
          average_observed_after_ai_seconds: 61.4
        }
      }
    },
    gate: {
      mode: "SHADOW_ONLY",
      status: identity.provider === "openai" ? "PASS" : "FAIL",
      failures: identity.provider === "openai" ? [] : ["ROI", "MAX_DRAWDOWN"]
    },
    equity_curve: [
      { occurred_at: "2026-08-10T10:00:00Z", entry_type: "EVENT_FUNDED", equity: 10000, cash: 10000, locked: 0, realized_pnl_delta: 0 },
      { occurred_at: "2026-08-12T11:00:00Z", entry_type: "BET_SETTLED_WIN", equity: 10700, cash: 10700, locked: 0, realized_pnl_delta: 700 },
      { occurred_at: "2026-08-15T13:00:00Z", entry_type: "BET_SETTLED_LOSS", equity: 10200, cash: 10200, locked: 0, realized_pnl_delta: -500 },
      { occurred_at: "2026-08-17T16:00:00Z", entry_type: "BET_SETTLED_WIN", equity: 10000 + pnl, cash: 10000 + pnl, locked: 0, realized_pnl_delta: pnl - 200 }
    ]
  };
}

const eventQuality = {
  quality_report_version: "tournament-quality-v1",
  gate_mode: "SHADOW_ONLY",
  canonical_event_id: "event-ti",
  policy: {
    min_settled_maps: 20,
    min_settled_bets: 10,
    min_prediction_samples: 20,
    min_clv_samples: 10,
    min_market_comparison_samples: 20,
    min_roi: 0,
    min_average_clv: 0,
    min_brier_improvement_vs_market: 0,
    max_drawdown_pct: 0.3
  },
  experiments: [eventExperiment(gptIdentity, "account-gpt", 1800), eventExperiment(deepseekIdentity, "account-deepseek", -400)]
};

const positions = {
  canonical_event_id: "event-ti",
  account_id: "account-gpt",
  experiment: gptIdentity,
  positions: [
    {
      id: "position-1",
      ai_decision_id: "decision-1234567890",
      canonical_series_id: "series-1234567890",
      canonical_map_id: "map-1234567890",
      map_number: 2,
      action: "BUY_A",
      team_a: { id: "team-spirit", name: "Team Spirit" },
      team_b: { id: "team-aurora", name: "Aurora" },
      selected_team: { id: "team-spirit", name: "Team Spirit" },
      cash_before: 10700,
      stake: 700,
      odds: 2.1,
      status: "WON",
      rejection_reason: null,
      payout: 1470,
      realized_pnl: 770,
      opened_at: "2026-08-17T14:01:00Z",
      settled_at: "2026-08-17T15:12:00Z"
    },
    {
      id: "position-2",
      ai_decision_id: "decision-rejected",
      canonical_series_id: "series-1234567890",
      canonical_map_id: "map-2234567890",
      map_number: 3,
      action: "BUY_B",
      team_a: { id: "team-spirit", name: "Team Spirit" },
      team_b: { id: "team-aurora", name: "Aurora" },
      selected_team: { id: "team-aurora", name: "Aurora" },
      cash_before: 11470,
      stake: 900,
      odds: null,
      status: "REJECTED",
      rejection_reason: "MARKET_NOT_EXECUTABLE",
      payout: null,
      realized_pnl: null,
      opened_at: "2026-08-17T16:01:00Z",
      settled_at: null
    }
  ]
};

async function mockPerformanceApi(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        authenticated: true,
        user: {
          id: "99999999-9999-9999-9999-999999999999",
          email: "pro@example.com",
          email_verified_at: "2026-08-15T10:00:00Z",
          created_at: "2026-08-15T10:00:00Z"
        },
        entitlements: ["ai_decisions"],
        grants: []
      })
    });
  });
  await page.route("**/api/review/ai-quality/leaderboard", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(leaderboard) });
  });
  await page.route("**/api/review/events/event-ti/ai-quality", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(eventQuality) });
  });
  await page.route("**/api/review/events/event-ti/ai-quality/positions**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(positions) });
  });
  await page.route("**/api/review/events/event-dreamleague/ai-quality", async (route) => {
    const payload = { ...eventQuality, canonical_event_id: "event-dreamleague", experiments: [eventExperiment(gptIdentity, "account-gpt-dl", 800)] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
  await page.route("**/api/review/events/event-dreamleague/ai-quality/positions**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...positions, canonical_event_id: "event-dreamleague", account_id: "account-gpt-dl" }) });
  });
}

test("compares AI portfolios and drills into an auditable event position", async ({ page }) => {
  await mockPerformanceApi(page);
  await page.goto("/performance");

  await expect(page.getByRole("heading", { name: "AI 表现榜", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI 盈利与质量" })).toBeVisible();
  await expect(page.getByText("跨赛事 Shadow 排行")).toBeVisible();
  await expect(page.getByText(/排序规则：已实现 ROI 从高到低/)).toBeVisible();
  await expect(page.getByText("不代表真实下注", { exact: true })).toBeVisible();
  await expect(page.getByText("SAME STARTING BANKROLL · SHADOW SETTLEMENT", { exact: true })).toBeHidden();
  await expect(page.getByText("REAL SETTLEMENT", { exact: true })).toHaveCount(0);

  const gptRow = page.getByRole("button", { name: /#1 GPT gpt-5\.6/ });
  const deepseekRow = page.getByRole("button", { name: /#2 DeepSeek deepseek-reasoner/ });
  await expect(gptRow).toContainText("13%");
  await expect(gptRow).toContainText("+2,600");
  await expect(deepseekRow).toContainText("-4%");
  await expect(deepseekRow).toContainText("−400");
  await expect(page.getByText("The International", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("PASS", { exact: true })).toBeVisible();
  await expect(page.getByText("22/20", { exact: true })).toBeVisible();
  await expect(page.getByText("T+30s", { exact: true })).toBeVisible();
  await expect(page.getByText(/纸面 Edge 保留率/).first()).toBeVisible();
  await expect(page.getByText("Brier 改善 vs 市场", { exact: true })).toBeVisible();
  await expect(page.getByText("+0.025", { exact: true })).toBeVisible();

  const positionButton = page.getByRole("button", { name: /MAP 2.*Team Spirit/ });
  await expect(positionButton).toContainText("WON");
  await expect(positionButton).toContainText("详情");
  await positionButton.click();
  await expect(positionButton).toContainText("收起");
  await expect(page.getByText("10,700", { exact: true })).toBeVisible();
  await expect(page.getByText(/decision…7890/)).toBeVisible();

  await page.getByRole("textbox", { name: "搜索 AI" }).fill("DeepSeek");
  await expect(page.locator(".performance-selected-summary")).toContainText("DeepSeek");
  await expect(page.locator(".performance-selected-summary")).not.toContainText("GPT");
  await expect(page.getByRole("button", { name: /#1 GPT gpt-5\.6/ })).toHaveCount(0);
  await expect(page.getByText("FAIL", { exact: true })).toBeVisible();
  await expect(page.getByText("ROI 未达标", { exact: true })).toBeVisible();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("keeps ranking semantics and position audit discoverable at tablet width", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await mockPerformanceApi(page);
  await page.goto("/performance");

  const gptRow = page.getByRole("button", { name: /#1 GPT gpt-5\.6/ });
  await expect(gptRow).toContainText("13%");
  await expect(page.locator(".performance-col-events", { hasText: "赛事" })).toBeVisible();
  await expect(page.getByText("PASS", { exact: true })).toBeVisible();

  const positionButton = page.getByRole("button", { name: /MAP 2.*Team Spirit/ });
  await expect(positionButton).toContainText("WON");
  await expect(positionButton).toContainText("详情");
  await positionButton.click();
  await expect(page.getByText("模拟成交前现金", { exact: true })).toBeVisible();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});