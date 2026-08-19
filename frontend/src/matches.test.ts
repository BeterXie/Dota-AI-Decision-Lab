import { describe, expect, it } from "vitest";
import type { MapSummary } from "./api";
import type { AuthSessionState } from "./authApi";
import { aiAccessScope, findMatchByRoute, matchHref, matchIdFromPath } from "./matches";

const match: MapSummary = {
  entity_type: "MAP",
  identity_status: "RESOLVED",
  phase: "LIVE",
  id: "summary-id",
  series_id: "series-1",
  canonical_event_id: "event-1",
  stage_key: "PAID_STAGE",
  canonical_map_id: "map-1",
  map_number: 1,
  valve_match_id: null,
  scheduled_at: null,
  provider_match_id: null,
  tournament_name: "TI15",
  round: null,
  raw_status: null,
  provider_observed_at: null,
  team_a: { id: "a", name: "Team A" },
  team_b: { id: "b", name: "Team B" },
  market: [],
  market_quality: null,
  draft: null,
  live: null,
  sync: null,
  latest_snapshot: null,
  decisions: []
};

function session(overrides: Partial<AuthSessionState>): AuthSessionState {
  return {
    enabled: true,
    authenticated: true,
    user: {
      id: "user-1",
      email: null,
      email_verified_at: null,
      created_at: "2026-08-18T00:00:00Z"
    },
    entitlements: [],
    grants: [],
    ...overrides
  };
}

describe("match routing", () => {
  it("uses canonical map identity in the public URL", () => {
    expect(matchHref(match)).toBe("/matches/map-1");
    expect(matchIdFromPath("/matches/map-1")).toBe("map-1");
    expect(findMatchByRoute([match], "map-1")).toBe(match);
  });

  it("falls back to summary identity when a canonical map is not resolved", () => {
    const unresolved = { ...match, id: "series-placeholder", canonical_map_id: null };
    expect(matchHref(unresolved)).toBe("/matches/series-placeholder");
    expect(findMatchByRoute([unresolved], "series-placeholder")).toBe(unresolved);
  });
});

describe("match AI access", () => {
  it("recognizes global, event, series and map access independently", () => {
    expect(aiAccessScope(session({ entitlements: ["ai_decisions"] }), match)).toBe("GLOBAL");
    expect(
      aiAccessScope(
        session({
          grants: [{ entitlement: "ai_decisions", scope_type: "SERIES", scope_ref: "series-1", campaign_key: null, starts_at: null, expires_at: null }]
        }),
        match
      )
    ).toBe("SERIES");
    expect(
      aiAccessScope(
        session({
          grants: [{ entitlement: "ai_decisions", scope_type: "EVENT", scope_ref: "event-1", campaign_key: null, starts_at: null, expires_at: null }]
        }),
        match
      )
    ).toBe("EVENT");
    expect(
      aiAccessScope(
        session({
          grants: [{ entitlement: "ai_decisions", scope_type: "MAP", scope_ref: "map-1", campaign_key: null, starts_at: null, expires_at: null }]
        }),
        match
      )
    ).toBe("MAP");
  });

  it("opens group-stage decisions as anonymous Free Access", () => {
    expect(aiAccessScope(undefined, { ...match, stage_key: "GROUP_STAGE" })).toBe("FREE");
  });

  it("keeps settled paid-stage decisions locked without a pass", () => {
    expect(aiAccessScope(undefined, { ...match, phase: "POSTMATCH" })).toBeNull();
    expect(aiAccessScope(session({}), { ...match, phase: "POSTMATCH" })).toBeNull();
  });

  it("does not treat unrelated grants as access", () => {
    expect(
      aiAccessScope(
        session({
          grants: [{ entitlement: "ai_decisions", scope_type: "MAP", scope_ref: "another-map", campaign_key: null, starts_at: null, expires_at: null }]
        }),
        match
      )
    ).toBeNull();
  });
});
