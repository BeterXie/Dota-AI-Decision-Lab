import { render, screen } from "@testing-library/react";
import React from "react";
import { expect, test } from "vitest";
import type { MapSummary } from "../api";
import { I18nProvider } from "../i18n";
import { DecisionStatusBanner } from "./DecisionStatusBanner";

function renderBanner(match: Partial<MapSummary>) {
  return render(
    <I18nProvider>
      <DecisionStatusBanner match={match as MapSummary} />
    </I18nProvider>
  );
}

test("AWAITING_RESULT is never presented as a finished map", () => {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "en");
  renderBanner({
    phase: "AWAITING_RESULT",
    latest_snapshot: { mode: "LIVE_BASIC", quality: { blockers: [], warnings: [] } }
  } as unknown as MapSummary);

  expect(screen.getByText("Live data stopped — awaiting result confirmation")).toBeInTheDocument();
  expect(screen.queryByText(/Map finished/i)).not.toBeInTheDocument();
});

test("a missing snapshot is never presented as an available decision", () => {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "en");
  renderBanner({ phase: "UNKNOWN", latest_snapshot: null } as unknown as MapSummary);

  expect(screen.getByText("No decision snapshot yet")).toBeInTheDocument();
  expect(screen.queryByText("Decision available with limitations")).not.toBeInTheDocument();
  expect(screen.getByText("NO SNAPSHOT")).toBeInTheDocument();
});
