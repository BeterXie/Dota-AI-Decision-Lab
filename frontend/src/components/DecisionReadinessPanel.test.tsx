import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AiReadinessPayload } from "../performanceApi";
import { DecisionReadinessPanel } from "./DecisionReadinessPanel";

const payload: AiReadinessPayload = {
  report_version: "decision-readiness-v1",
  generated_at: "2026-08-18T12:00:00Z",
  window: {
    from: "2026-08-11T12:00:00Z",
    to: "2026-08-18T12:00:00Z",
    lookback_hours: 168,
    future_series_included: false
  },
  scope: {
    source: "LIQUIPEDIA_BACKED_CANONICAL_SERIES",
    series_count: 3,
    series_limit: 250
  },
  stages: [
    { key: "scheduled", label: "SCHEDULED", count: 3, rate: 1, drop_count: 0 },
    { key: "market_linked", label: "MARKET_LINKED", count: 2, rate: 2 / 3, drop_count: 1 },
    { key: "market_ready", label: "MARKET_READY", count: 2, rate: 2 / 3, drop_count: 0 },
    { key: "map_identity", label: "MAP_IDENTITY", count: 2, rate: 2 / 3, drop_count: 0 },
    { key: "live_ready", label: "LIVE_READY", count: 2, rate: 2 / 3, drop_count: 0 },
    { key: "snapshot_ready", label: "SNAPSHOT_READY", count: 1, rate: 1 / 3, drop_count: 1 },
    { key: "ai_decision", label: "AI_DECISION", count: 1, rate: 1 / 3, drop_count: 0 },
    { key: "result_ready", label: "RESULT_READY", count: 1, rate: 1 / 3, drop_count: 0 },
    { key: "evaluated", label: "EVALUATED", count: 1, rate: 1 / 3, drop_count: 0 }
  ],
  failure_reasons: [
    { stage: "market_linked", reason: "MARKET_IDENTITY_MISSING", count: 1, rate: 1 / 3 },
    { stage: "snapshot_ready", reason: "DRAFT_INCOMPLETE", count: 1, rate: 1 / 3 }
  ],
  series: [
    {
      canonical_series_id: "series-evaluated",
      canonical_event_id: "event-ti",
      event_name: "The International 2026",
      scheduled_at: "2026-08-18T09:00:00Z",
      team_a: { id: "liquid", name: "Team Liquid" },
      team_b: { id: "spirit", name: "Team Spirit" },
      best_of: 3,
      current_stage: "EVALUATED",
      blocker: null,
      facts: {},
      counts: { maps: 2, live_maps: 2, snapshots: 2, successful_decision_snapshots: 2, result_maps: 2, evaluated_snapshots: 2 },
      ai_status_counts: { SUCCESS: 2 }
    },
    {
      canonical_series_id: "series-raybet",
      canonical_event_id: "event-ti",
      event_name: "The International 2026",
      scheduled_at: "2026-08-18T10:00:00Z",
      team_a: { id: "aurora", name: "Aurora" },
      team_b: { id: "xg", name: "Xtreme Gaming" },
      best_of: 3,
      current_stage: "SCHEDULED",
      blocker: { stage: "market_linked", reason: "MARKET_IDENTITY_MISSING" },
      facts: {},
      counts: { maps: 0, live_maps: 0, snapshots: 0, successful_decision_snapshots: 0, result_maps: 0, evaluated_snapshots: 0 },
      ai_status_counts: {}
    },
    {
      canonical_series_id: "series-draft",
      canonical_event_id: "event-ti",
      event_name: "The International 2026",
      scheduled_at: "2026-08-18T11:00:00Z",
      team_a: { id: "falcons", name: "Team Falcons" },
      team_b: { id: "tundra", name: "Tundra Esports" },
      best_of: 3,
      current_stage: "LIVE_READY",
      blocker: { stage: "snapshot_ready", reason: "DRAFT_INCOMPLETE" },
      facts: {},
      counts: { maps: 1, live_maps: 1, snapshots: 0, successful_decision_snapshots: 0, result_maps: 0, evaluated_snapshots: 0 },
      ai_status_counts: {}
    }
  ]
};

function hasTeamPair(first: string, second: string) {
  return (_content: string, element: Element | null) =>
    element?.tagName === "STRONG" &&
    element.textContent?.includes(first) === true &&
    element.textContent?.includes(second) === true;
}

describe("DecisionReadinessPanel", () => {
  it("shows the real-match funnel and filters trace rows by blocker", () => {
    render(
      <DecisionReadinessPanel
        data={payload}
        loading={false}
        error={false}
        onRetry={() => undefined}
        locale="zh-CN"
      />
    );

    expect(screen.getByText("真实比赛预测就绪度")).toBeTruthy();
    expect(screen.getAllByText("33%").length).toBeGreaterThan(0);
    expect(screen.getByText(hasTeamPair("Aurora", "Xtreme Gaming"))).toBeTruthy();
    expect(screen.getByText(hasTeamPair("Team Falcons", "Tundra Esports"))).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /市场身份未匹配/ }));

    expect(screen.getByText(hasTeamPair("Aurora", "Xtreme Gaming"))).toBeTruthy();
    expect(screen.queryByText(hasTeamPair("Team Falcons", "Tundra Esports"))).toBeNull();
  });
});
