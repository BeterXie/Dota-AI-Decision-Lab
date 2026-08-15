import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test } from "vitest";
import type { MapDetail } from "../api";
import { I18nProvider } from "../i18n";
import { EvaluationCard } from "./EvaluationCard";

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
});

afterEach(() => {
  cleanup();
});

test("shows settled virtual P&L per AI with stake and ROI", () => {
  const match = {
    id: "map-1",
    canonical_map_id: "map-1",
    team_a: { id: "team-a", name: "Team A" },
    team_b: { id: "team-b", name: "Team B" },
    decisions: [],
    checkpoint_decisions: [
      {
        id: "d1",
        provider: "openai",
        model: "gpt-test",
        stake: 100,
        evaluation: { virtual_pnl: 60 },
      },
      {
        id: "d2",
        provider: "openai",
        model: "gpt-test",
        stake: 150,
        evaluation: { virtual_pnl: -10 },
      }
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
});

test("shows unsettled virtual P&L before results are available", () => {
  const match = {
    id: "map-2",
    canonical_map_id: "map-2",
    team_a: { id: "team-a", name: "Team A" },
    team_b: { id: "team-b", name: "Team B" },
    decisions: [],
    checkpoint_decisions: [
      {
        id: "d1",
        provider: "openai",
        model: "gpt-test",
        stake: 100,
        evaluation: null
      }
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

  expect(screen.getByText("未结算")).toBeInTheDocument();
});
