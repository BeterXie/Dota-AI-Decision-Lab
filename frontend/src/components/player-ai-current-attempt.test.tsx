import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AiDecision } from "../api";
import { I18nProvider } from "../i18n";
import { PlayerAiDecisionPanel } from "./PlayerAiDecisionPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function record(overrides: Partial<AiDecision>): AiDecision {
  return {
    id: "decision-1",
    snapshot_id: "snapshot-1",
    provider: "openai",
    model: "gpt-test",
    model_version: "gpt-test",
    prompt_version: "decision-analyst-v4",
    decision_policy_version: "shadow-decision-v2",
    snapshot_hash: "snapshot-hash",
    request_started_at: "2026-08-15T12:00:00Z",
    response_received_at: "2026-08-15T12:00:10Z",
    parse_status: "SUCCESS",
    latency_seconds: 10,
    decision: {
      action: "BUY_A",
      confidence: 0.7,
      fair_probability_a: 0.61,
      market_assessment: "UNDERPRICED",
      primary_reasons: ["fixture"],
      counter_arguments: [],
      data_quality_concerns: [],
      blockers: []
    },
    error: null,
    ...overrides
  };
}

test("keeps canonical success visible while exposing a newer current timeout", async () => {
  const canonical = record({
    id: "old-success",
    prompt_version: "decision-analyst-v4",
    request_started_at: "2026-08-15T12:00:00Z"
  });
  const timeout = record({
    id: "current-timeout",
    prompt_version: "decision-analyst-v5",
    request_started_at: "2026-08-15T12:01:00Z",
    response_received_at: "2026-08-15T12:01:50Z",
    parse_status: "TIMEOUT",
    decision: null,
    error: "provider exceeded 50.0s timeout"
  });
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ decisions: [canonical, timeout] })
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <I18nProvider>
      <PlayerAiDecisionPanel
        decisions={[canonical]}
        currentSnapshotId="snapshot-1"
        access={{ authEnabled: true, authenticated: true, entitled: true, loading: false }}
        analysisAvailable
        completedModels={1}
        onLogin={vi.fn()}
      />
    </I18nProvider>
  );

  expect(screen.getAllByText("BUY A").length).toBeGreaterThan(0);
  expect(await screen.findByText("Current experiment status")).toBeInTheDocument();
  const currentStatus = screen.getByText(
    (_text, element) =>
      element?.tagName === "SPAN" &&
      (element.textContent ?? "").includes("GPT TIMEOUT · decision-analyst-v5")
  );
  expect(currentStatus).toHaveTextContent("provider exceeded 50.0s timeout");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/snapshots/snapshot-1",
    expect.objectContaining({ cache: "no-store" })
  );
});
