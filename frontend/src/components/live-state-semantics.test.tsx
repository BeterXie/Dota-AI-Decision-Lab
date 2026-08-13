import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import type { MapSummary } from "../api";
import { I18nProvider } from "../i18n";
import { LiveStateCard } from "./LiveStateCard";

test("effective state age controls stale presentation", () => {
  const match = {
    live: {
      game_time_seconds: 1200,
      radiant_kills: 8,
      dire_kills: 9,
      radiant_nw_lead: -3000,
      first_blood: "dire",
      received_at: "2026-08-13T12:00:00Z",
      last_message_received_at: "2026-08-13T12:00:00Z",
      last_state_change_received_at: "2026-08-13T11:59:00Z",
      message_age_seconds: 1,
      effective_state_age_seconds: 60,
      connection_id: "fixture",
      reconnect_generation: 0
    },
    sync: { status: "SAFE" }
  } as MapSummary;

  const { container } = render(<I18nProvider><LiveStateCard match={match} /></I18nProvider>);
  expect(container.querySelector(".stale-warning-banner")).not.toBeNull();
  expect(container.textContent).toContain("Dire +3,000");
});
