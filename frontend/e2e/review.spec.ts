import { expect, test, type Page } from "playwright/test";

const reviewPayload = {
  summary: {
    settled_maps: 2,
    rosh: {
      reference_minute: 30,
      pure: { evaluated: 2, correct: 2, accuracy: 1 },
      adjusted: { evaluated: 2, correct: 1, accuracy: 0.5 }
    },
    ai: [
      {
        provider: "openai",
        model: "gpt-5.6",
        rounds: 4,
        buy_decisions: 3,
        settled_buy_decisions: 3,
        correct_buy_decisions: 2,
        buy_accuracy: 2 / 3,
        average_brier: 0.18,
        average_log_loss: 0.53,
        unit_pnl: 0.7,
        unit_bets: 3,
        unit_roi: 0.7 / 3,
        latest: {
          snapshot_id: "snapshot-2",
          decision_at: "2026-08-15T12:20:00Z",
          action: "BUY_A",
          fair_probability_a: 0.62,
          confidence: 0.74,
          market_assessment: "UNDERPRICED"
        }
      }
    ],
    odds: { eligible_maps: 2, closing_captured: 1, closing_coverage: 0.5 }
  },
  matches: [
    {
      canonical_map_id: "map-1",
      series_id: "series-1",
      map_number: 1,
      valve_match_id: 9000000001,
      scheduled_at: "2026-08-15T11:00:00Z",
      settled_at: "2026-08-15T13:00:00Z",
      tournament_name: "The International",
      team_a: { id: "team-a", name: "Aurora" },
      team_b: { id: "team-b", name: "Spirit" },
      winner_team_id: "team-a",
      rosh: {
        snapshot_id: "snapshot-1",
        decision_at: "2026-08-15T11:30:00Z",
        reference_minute: 30,
        model_version: "rosh-v1",
        data_version: "stratz-v1",
        radiant_team_id: "team-a",
        dire_team_id: "team-b",
        points: [
          { minute: 20, pure: { edge_pp: 2, favored_team_id: "team-a", correct: true }, adjusted: { edge_pp: 1, favored_team_id: "team-a", correct: true } },
          { minute: 30, pure: { edge_pp: 4, favored_team_id: "team-a", correct: true }, adjusted: { edge_pp: -2, favored_team_id: "team-b", correct: false } },
          { minute: 40, pure: { edge_pp: 1, favored_team_id: "team-a", correct: true }, adjusted: { edge_pp: -4, favored_team_id: "team-b", correct: false } }
        ],
        reference: {
          minute: 30,
          pure: { edge_pp: 4, favored_team_id: "team-a", correct: true },
          adjusted: { edge_pp: -2, favored_team_id: "team-b", correct: false }
        }
      },
      ai: [
        {
          provider: "openai",
          model: "gpt-5.6",
          rounds: 2,
          buy_decisions: 2,
          settled_buy_decisions: 2,
          correct_buy_decisions: 1,
          buy_accuracy: 0.5,
          average_brier: 0.2,
          average_log_loss: 0.58,
          unit_pnl: 0.1,
          unit_bets: 2,
          unit_roi: 0.05,
          latest: {
            snapshot_id: "snapshot-2",
            decision_at: "2026-08-15T12:20:00Z",
            action: "BUY_A",
            fair_probability_a: 0.62,
            confidence: 0.74,
            market_assessment: "UNDERPRICED"
          }
        }
      ],
      odds: {
        start: { odds_a: 2.2, odds_b: 1.7, fair_probability_a: 0.435, fair_probability_b: 0.565, observed_at: "2026-08-15T11:30:00Z" },
        end: { odds_a: 1.8, odds_b: 2.05, fair_probability_a: 0.532, fair_probability_b: 0.468, observed_at: "2026-08-15T12:58:00Z" },
        end_kind: "CLOSING",
        team_a_fair_probability_change_pp: 9.7
      }
    },
    {
      canonical_map_id: "map-2",
      series_id: "series-1",
      map_number: 2,
      valve_match_id: 9000000002,
      scheduled_at: "2026-08-15T13:30:00Z",
      settled_at: "2026-08-15T15:00:00Z",
      tournament_name: "The International",
      team_a: { id: "team-a", name: "Aurora" },
      team_b: { id: "team-b", name: "Spirit" },
      winner_team_id: "team-b",
      rosh: {
        snapshot_id: "snapshot-3",
        decision_at: "2026-08-15T13:50:00Z",
        reference_minute: 30,
        model_version: "rosh-v1",
        data_version: "stratz-v1",
        radiant_team_id: "team-b",
        dire_team_id: "team-a",
        points: [
          { minute: 20, pure: { edge_pp: 1.5, favored_team_id: "team-b", correct: true }, adjusted: { edge_pp: 2, favored_team_id: "team-b", correct: true } },
          { minute: 30, pure: { edge_pp: 3, favored_team_id: "team-b", correct: true }, adjusted: { edge_pp: 4, favored_team_id: "team-b", correct: true } },
          { minute: 40, pure: { edge_pp: 2, favored_team_id: "team-b", correct: true }, adjusted: { edge_pp: 3, favored_team_id: "team-b", correct: true } }
        ],
        reference: {
          minute: 30,
          pure: { edge_pp: 3, favored_team_id: "team-b", correct: true },
          adjusted: { edge_pp: 4, favored_team_id: "team-b", correct: true }
        }
      },
      ai: [
        {
          provider: "openai",
          model: "gpt-5.6",
          rounds: 2,
          buy_decisions: 1,
          settled_buy_decisions: 1,
          correct_buy_decisions: 1,
          buy_accuracy: 1,
          average_brier: 0.16,
          average_log_loss: 0.48,
          unit_pnl: 0.6,
          unit_bets: 1,
          unit_roi: 0.6,
          latest: {
            snapshot_id: "snapshot-4",
            decision_at: "2026-08-15T14:30:00Z",
            action: "BUY_B",
            fair_probability_a: 0.4,
            confidence: 0.7,
            market_assessment: "OVERPRICED"
          }
        }
      ],
      odds: {
        start: { odds_a: 1.85, odds_b: 2.05, fair_probability_a: 0.526, fair_probability_b: 0.474, observed_at: "2026-08-15T13:50:00Z" },
        end: { odds_a: 2.1, odds_b: 1.78, fair_probability_a: 0.458, fair_probability_b: 0.542, observed_at: "2026-08-15T14:30:00Z" },
        end_kind: "LATEST_DECISION",
        team_a_fair_probability_change_pp: -6.8
      }
    }
  ],
  methodology: {
    rosh_reference_minute: 30,
    rosh_review_minutes: [20, 30, 40],
    rosh_source: "EARLIEST_IMMUTABLE_DECISION_SNAPSHOT_WITH_RESOLVED_SIDES",
    ai_round_rule: "LATEST_SUCCESS_PER_SNAPSHOT_PROVIDER_MODEL",
    odds_start: "EARLIEST_VALID_DECISION_SNAPSHOT_MARKET",
    odds_end: "CLOSING_CAPTURE_OR_LATEST_VALID_DECISION_SNAPSHOT"
  }
};

async function mockReviewApi(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ enabled: false, authenticated: false, user: null })
    });
  });
  await page.route("**/api/review/matches**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(reviewPayload)
    });
  });
}

test("renders auditable post-match review ledger", async ({ page }) => {
  await mockReviewApi(page);
  await page.goto("/review");

  await expect(page.getByRole("heading", { name: "比赛复盘" })).toBeVisible();
  await expect(page.getByText("R.O.S.H. 纯阵容 30m", { exact: true })).toBeVisible();
  await expect(page.getByText("R.O.S.H. 选手修正 30m", { exact: true })).toBeVisible();
  await expect(page.getByText("Aurora +4.0pp ✓", { exact: true })).toBeVisible();
  await expect(page.getByText("Spirit +2.0pp ✕", { exact: true })).toBeVisible();
  await expect(page.getByText("🏆 Aurora", { exact: true })).toBeVisible();
  await expect(page.getByText("🏆 Spirit", { exact: true })).toBeVisible();
  await expect(page.getByText("BUY A · Aurora", { exact: true })).toBeVisible();
  await expect(page.getByText("BUY B · Spirit", { exact: true })).toBeVisible();
  await expect(page.getByText("2.20 → 1.80", { exact: true })).toBeVisible();
  await expect(page.getByText(/A fair p \+9\.7pp · 收盘/)).toBeVisible();
  await expect(page.getByText(/A fair p -6\.8pp · 最后决策/)).toBeVisible();

  await page.getByRole("button", { name: "ROSH 错误" }).click();
  await expect(page.getByText("🏆 Aurora", { exact: true })).toBeVisible();
  await expect(page.getByText("🏆 Spirit", { exact: true })).toHaveCount(0);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});
