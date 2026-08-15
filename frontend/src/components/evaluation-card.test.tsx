import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test } from "vitest";
import type { AiDecision, MapDetail } from "../api";
import { I18nProvider } from "../i18n";
import { EvaluationCard } from "./EvaluationCard";

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
});

afterEach(() => {
  cleanup();
});

function decisionFixture(
  id: string,
  overrides: Partial<AiDecision> & Pick<AiDecision, "evaluation">
): AiDecision {
  return {
    id,
    snapshot_id: "snap-1",
    provider: "openai",
    model: "gpt-test",
    model_version: "gpt-test-v1",
    prompt_version: "prompt-v1",
    decision_policy_version: "policy-v1",
    snapshot_hash: "snapshot-hash",
    request_started_at: "2026-08-15T12:00:00Z",
    response_received_at: "2026-08-15T12:00:01Z",
    parse_status: "SUCCESS",
    latency_seconds: 0.8,
    decision: {
      action: "BUY_A",
      confidence: 0.7,
      fair_probability_a: 0.6,
      primary_reasons: ["fixture"],
      counter_arguments: [],
      data_quality_concerns: [],
      blockers: []
    },
    error: null,
    ...overrides
  };
}

test("shows settled virtual P&L per AI with stake and ROI", () => {
  const match = {
    id: "map-1",
    canonical_map_id: "map-1",
    team_a: { id: "team-a", name: "Team A" },
    team_b: { id: "team-b", name: "Team B" },
    decisions: [],
    checkpoint_decisions: [
      decisionFixture("d1", {
        stake: 100,
        evaluation: { virtual_pnl: 60, unit_pnl: 0.6 }
      }),
      decisionFixture("d2", {
        snapshot_id: "snap-2",
        stake: 150,
        evaluation: { virtual_pnl: -10 }
      })
    ],
    market_timeline: [],
    future_odds: [],
    result: null,
    result_evidence: []
  } as unknown as MapDetail;

  render(
    <I18nProvider>
      <EvaluationCard match={match} />
    </I18nProvider>
  );

  expect(screen.getByText("AI 虚拟投注结算（影子资金）")).toBeInTheDocument();
  expect(screen.getByText("+50")).toBeInTheDocument();
  expect(screen.getByText("250")).toBeInTheDocument();
  expect(screen.getByText("20%")).toBeInTheDocument();
  expect(screen.getByText("标准化 1 单位盈亏")).toBeInTheDocument();
  expect(screen.getByText("+0.6")).toBeInTheDocument();
  expect(screen.getByText("标准化 1 单位 ROI")).toBeInTheDocument();
  expect(screen.getByText("60%")).toBeInTheDocument();
});

test("shows unsettled virtual P&L before results are available", () => {
  const match = {
    id: "map-2",
    canonical_map_id: "map-2",
    team_a: { id: "team-a", name: "Team A" },
    team_b: { id: "team-b", name: "Team B" },
    decisions: [],
    checkpoint_decisions: [
      decisionFixture("d1", {
        stake: 100,
        evaluation: null
      })
    ],
    market_timeline: [],
    future_odds: [],
    result: null,
    result_evidence: []
  } as unknown as MapDetail;

  render(
    <I18nProvider>
      <EvaluationCard match={match} />
    </I18nProvider>
  );

  expect(screen.getAllByText("未结算").length).toBeGreaterThan(0);
});
