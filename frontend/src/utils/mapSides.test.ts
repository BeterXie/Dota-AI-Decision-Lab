import { expect, test } from "vitest";
import type { MapDetail } from "../api";
import { resolveVerifiedMapSides } from "./mapSides";

function detail(sideIdentity: Record<string, unknown>): MapDetail {
  return {
    team_a: { id: "team-a", name: "Series A" },
    team_b: { id: "team-b", name: "Series B" },
    snapshot_payload: {
      identity: {
        side_identity: sideIdentity as MapDetail["snapshot_payload"] extends infer Payload
          ? Payload extends { identity?: infer Identity }
            ? Identity extends { side_identity?: infer Side }
              ? Side
              : never
            : never
          : never
      }
    }
  } as MapDetail;
}

test("maps verified radiant and dire ids without using series order", () => {
  const sides = resolveVerifiedMapSides(
    detail({
      status: "RESOLVED",
      radiant_team_id: "team-b",
      dire_team_id: "team-a",
      source: "DLTV_DB_IS_RADIANT",
      confidence: 1,
      observed_at: "2026-08-13T12:00:00Z",
      raw_event_id: "raw-1",
      blocker: null
    })
  );

  expect(sides?.radiant.name).toBe("Series B");
  expect(sides?.radiant.seriesSide).toBe("B");
  expect(sides?.dire.name).toBe("Series A");
  expect(sides?.dire.seriesSide).toBe("A");
});

test("rejects unresolved, conflicting, or non-canonical side ids", () => {
  expect(
    resolveVerifiedMapSides(
      detail({
        status: "UNRESOLVED",
        radiant_team_id: null,
        dire_team_id: null,
        source: null,
        confidence: null,
        observed_at: null,
        raw_event_id: null,
        blocker: "SIDE_IDENTITY_UNRESOLVED"
      })
    )
  ).toBeNull();

  expect(
    resolveVerifiedMapSides(
      detail({
        status: "RESOLVED",
        radiant_team_id: "not-this-series",
        dire_team_id: "team-a",
        source: "DLTV_DB_IS_RADIANT",
        confidence: 1,
        observed_at: "2026-08-13T12:00:00Z",
        raw_event_id: "raw-1",
        blocker: null
      })
    )
  ).toBeNull();
});
