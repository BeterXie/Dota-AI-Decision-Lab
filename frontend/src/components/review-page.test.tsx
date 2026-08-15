import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { ReviewPage } from "./ReviewPage";

beforeEach(() => {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function response(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

function renderReview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <ReviewPage />
      </I18nProvider>
    </QueryClientProvider>
  );
}

const fixture = {
  summary: {
    settled_maps: 1,
    rosh: {
      reference_minute: 30,
      pure: { evaluated: 1, correct: 1, accuracy: 1 },
      adjusted: { evaluated: 1, correct: 0, accuracy: 0 }
    },
    ai: [
      {
        provider: "openai",
        model: "gpt-test",
        rounds: 2,
        buy_decisions: 2,
        settled_buy_decisions: 2,
        correct_buy_decisions: 1,
        buy_accuracy: 0.5,
        average_brier: 0.19,
        average_log_loss: 0.55,
        unit_pnl: 0.2,
        unit_bets: 2,
        unit_roi: 0.1,
        latest: {
          snapshot_id: "snap-2",
          decision_at: "2026-08-15T12:20:00Z",
          action: "BUY_A",
          fair_probability_a: 0.62,
          confidence: 0.74,
          market_assessment: "UNDERPRICED"
        }
      }
    ],
    odds: { eligible_maps: 1, closing_captured: 1, closing_coverage: 1 }
  },
  matches: [
    {
      canonical_map_id: "map-1",
      series_id: "series-1",
      map_number: 2,
      valve_match_id: 12345,
      scheduled_at: "2026-08-15T11:00:00Z",
      settled_at: "2026-08-15T13:00:00Z",
      tournament_name: "The International",
      team_a: { id: "team-a", name: "Aurora" },
      team_b: { id: "team-b", name: "Spirit" },
      winner_team_id: "team-a",
      rosh: {
        snapshot_id: "snap-1",
        decision_at: "2026-08-15T11:30:00Z",
        reference_minute: 30,
        model_version: "rosh-v1",
        data_version: "data-v1",
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
          model: "gpt-test",
          rounds: 2,
          buy_decisions: 2,
          settled_buy_decisions: 2,
          correct_buy_decisions: 1,
          buy_accuracy: 0.5,
          average_brier: 0.19,
          average_log_loss: 0.55,
          unit_pnl: 0.2,
          unit_bets: 2,
          unit_roi: 0.1,
          latest: {
            snapshot_id: "snap-2",
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

test("renders winner, R.O.S.H., AI decisions and odds movement in one ledger", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(fixture)));
  renderReview();

  expect((await screen.findAllByText("Aurora")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Spirit").length).toBeGreaterThan(0);
  expect(screen.getByText("🏆 Aurora")).toBeInTheDocument();
  expect(screen.getByText(/Aurora \+4\.0pp ✓/)).toBeInTheDocument();
  expect(screen.getByText(/Spirit \+2\.0pp ✕/)).toBeInTheDocument();
  expect(screen.getByText(/BUY A · Aurora/)).toBeInTheDocument();
  expect(screen.getByText("2.20 → 1.80")).toBeInTheDocument();
  expect(screen.getByText(/A fair p \+9\.7pp/)).toBeInTheDocument();
  expect(screen.getAllByText("1/1").length).toBeGreaterThan(0);
});

test("filters the ledger to R.O.S.H. misses", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(fixture)));
  renderReview();

  expect((await screen.findAllByText("Aurora")).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "ROSH 错误" }));
  expect(screen.getAllByText("Aurora").length).toBeGreaterThan(0);

  const search = screen.getByPlaceholderText("搜索队伍 / 赛事");
  fireEvent.change(search, { target: { value: "不存在" } });
  expect(screen.getByText("当前筛选条件没有比赛")).toBeInTheDocument();
});
