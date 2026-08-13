import type { MapDetail, MapSummary } from "../api";

export interface VerifiedMapSideTeam {
  id: string;
  name: string;
  seriesSide: "A" | "B";
}

export interface VerifiedMapSides {
  radiant: VerifiedMapSideTeam;
  dire: VerifiedMapSideTeam;
  source: string | null;
  confidence: number | null;
  observedAt: string | null;
}

export function resolveVerifiedMapSides(match: MapSummary | MapDetail): VerifiedMapSides | null {
  if (!("snapshot_payload" in match)) return null;
  const sideIdentity = match.snapshot_payload?.identity?.side_identity;
  const teamA = match.team_a;
  const teamB = match.team_b;
  if (
    !sideIdentity ||
    sideIdentity.status !== "RESOLVED" ||
    !sideIdentity.radiant_team_id ||
    !sideIdentity.dire_team_id ||
    !teamA ||
    !teamB ||
    teamA.id === teamB.id ||
    sideIdentity.radiant_team_id === sideIdentity.dire_team_id
  ) {
    return null;
  }

  const byId = new Map<string, VerifiedMapSideTeam>([
    [teamA.id, { id: teamA.id, name: teamA.name, seriesSide: "A" }],
    [teamB.id, { id: teamB.id, name: teamB.name, seriesSide: "B" }]
  ]);
  const radiant = byId.get(sideIdentity.radiant_team_id);
  const dire = byId.get(sideIdentity.dire_team_id);
  if (!radiant || !dire || radiant.id === dire.id) return null;

  return {
    radiant,
    dire,
    source: sideIdentity.source,
    confidence: sideIdentity.confidence,
    observedAt: sideIdentity.observed_at
  };
}
