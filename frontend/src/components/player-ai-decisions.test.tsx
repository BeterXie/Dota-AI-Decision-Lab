import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AiDecision } from "../api";
import { I18nProvider } from "../i18n";
import { PlayerAiDecisionStrip } from "./PlayerAiDecisionStrip";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function decision(overrides: Partial<AiDecision>): AiDecision {
  return {
    id: "d1",
    snapshot_id: "s1",
    provider: "openai",
    model: "gpt-test",
    model_version: "gpt-test",
    prompt_version: "decision-analyst-v4",
    decision_policy_version: "shadow-decision-v2",
    snapshot_hash: "snapshot-hash",
    request_started_at: "2026-08-12T12:00:00Z",
    response_received_at: "2026-08-12T12:00:02Z",
    parse_status: "SUCCESS",
    latency_seconds: 0.8,
    decision: {
      action: "NO_BUY",
      confidence: 0.5,
      fair_probability_a: null,
      primary_reasons: ["No edge"],
      counter_arguments: [],
      data_quality_concerns: [],
      blockers: []
    },
    error: null,
    ...overrides
  };
}

function renderStrip(decisions: AiDecision[]) {
  return render(
    <I18nProvider>
      <PlayerAiDecisionStrip decisions={decisions} />
    </I18nProvider>
  );
}

test("shows one fixed AI card per model and opens all rounds in one modal", () => {
  const first = decision({
    id: "d1",
    snapshot_id: "s1",
    snapshot_decision_at: "2026-08-12T12:00:00Z",
    snapshot_mode: "LIVE_BASIC",
    bankroll_before: 10_000,
    evaluation: { virtual_pnl: 50, virtual_odds: 1.85 },
    decision: {
      action: "BUY_A",
      confidence: 0.7,
      fair_probability_a: 0.61,
      primary_reasons: ["Draft and price align"],
      counter_arguments: ["Crossover risk"],
      data_quality_concerns: ["Legacy quality concern"],
      blockers: [],
      stake: 500
    }
  });
  const second = decision({
    id: "d2",
    snapshot_id: "s2",
    snapshot_decision_at: "2026-08-12T12:05:00Z",
    snapshot_mode: "LIVE_BASIC",
    bankroll_before: 9_500,
    evaluation: { virtual_pnl: -20, virtual_odds: 2.1 },
    decision: {
      action: "BUY_B",
      confidence: 0.6,
      fair_probability_a: 0.42,
      primary_reasons: ["Momentum flipped"],
      counter_arguments: [],
      data_quality_concerns: [],
      blockers: [],
      stake: 200
    }
  });

  renderStrip([first, second]);

  // One fixed card for GPT, not one card per round.
  expect(screen.getAllByText("GPT")).toHaveLength(1);
  expect(screen.getByText("2 rounds")).toBeInTheDocument();
  expect(screen.getAllByText("BUY B").length).toBeGreaterThan(0);
  expect(screen.queryByText("BUY A")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /GPT/ }));

  // Both rounds live inside the same modal.
  expect(screen.getAllByText(/Checkpoint ·/)).toHaveLength(2);
  expect(screen.getByText("BUY A")).toBeInTheDocument();
  expect(screen.getAllByText("BUY B").length).toBeGreaterThan(0);
  expect(screen.getAllByText("500").length).toBeGreaterThan(0);
  expect(screen.getAllByText("200").length).toBeGreaterThan(0);
  expect(screen.getAllByText("+50").length).toBeGreaterThan(0);
  expect(screen.getAllByText("-20").length).toBeGreaterThan(0);
  expect(screen.getAllByText("+30").length).toBeGreaterThan(0);
    expect(screen.getByText("10,030")).toBeInTheDocument();
    expect(screen.getByText("Final bankroll")).toBeInTheDocument();
  expect(screen.getByText("Draft and price align")).toBeInTheDocument();
  expect(screen.getByText("Momentum flipped")).toBeInTheDocument();
  expect(screen.queryByText("Crossover risk")).not.toBeInTheDocument();
  expect(screen.queryByText("Legacy quality concern")).not.toBeInTheDocument();
});

test("deduplicates repeated experiments on the same checkpoint", () => {
  const newer = decision({
    id: "d-new",
    snapshot_id: "s1",
    request_started_at: "2026-08-12T12:01:00Z",
    snapshot_decision_at: "2026-08-12T12:00:00Z",
    decision: { ...decision({}).decision, action: "NO_BUY" }
  });
  const older = decision({
    id: "d-old",
    snapshot_id: "s1",
    request_started_at: "2026-08-12T12:00:00Z",
    snapshot_decision_at: "2026-08-12T12:00:00Z",
    decision: { ...decision({}).decision, action: "BUY_A" }
  });

  renderStrip([newer, older]);

  expect(screen.getByText("1 round")).toBeInTheDocument();
  expect(screen.getAllByText("NO BUY").length).toBeGreaterThan(0);
  expect(screen.queryByText("BUY A")).not.toBeInTheDocument();
});



test("final bankroll is initial plus settled P&L only when every staked round is settled", () => {
  const settled = decision({
    id: "settled",
    snapshot_id: "s1",
    snapshot_decision_at: "2026-08-12T12:00:00Z",
    bankroll_before: 10_000,
    stake: 100,
    evaluation: { virtual_pnl: 100, virtual_odds: 2 },
    decision: { ...decision({}).decision, action: "BUY_A", stake: 100 }
  });
  const unsettled = decision({
    id: "unsettled",
    snapshot_id: "s2",
    snapshot_decision_at: "2026-08-12T12:05:00Z",
    bankroll_before: 9_900,
    stake: 200,
    evaluation: null,
    decision: { ...decision({}).decision, action: "BUY_B", stake: 200 }
  });

  renderStrip([settled, unsettled]);
  fireEvent.click(screen.getByRole("button", { name: /GPT/ }));

  expect(screen.queryByText("Final bankroll")).not.toBeInTheDocument();
  expect(screen.getByText("Current available bankroll")).toBeInTheDocument();
  expect(screen.getByText("9,700")).toBeInTheDocument();
  expect(screen.getByText("Pending unsettled stake")).toBeInTheDocument();
  expect(screen.getAllByText("200").length).toBeGreaterThan(0);
});
