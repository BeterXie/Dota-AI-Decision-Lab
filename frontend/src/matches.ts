import type { MapSummary } from "./api";
import type { AuthSessionState } from "./authApi";

export type AiAccessScope = "GLOBAL" | "EVENT" | "SERIES" | "MAP" | "FREE" | "POSTMATCH" | null;

const AI_DECISIONS_ENTITLEMENT = "ai_decisions";

export function matchHref(match: Pick<MapSummary, "id" | "canonical_map_id">): string {
  return `/matches/${encodeURIComponent(match.canonical_map_id || match.id)}`;
}

export function matchIdFromPath(pathname: string): string | null {
  const prefix = "/matches/";
  if (!pathname.startsWith(prefix)) return null;
  const segment = pathname.slice(prefix.length).split("/")[0];
  if (!segment) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

export function findMatchByRoute(matches: MapSummary[], routeId: string): MapSummary | null {
  const exactMatch =
    matches.find((match) => match.canonical_map_id === routeId) ??
    matches.find((match) => match.id === routeId);
  if (exactMatch) return exactMatch;

  const seriesMatches = matches.filter((match) => match.series_id === routeId);
  if (!seriesMatches.length) return null;
  return [...seriesMatches].sort(compareSeriesRouteMatches)[0];
}

const phasePriority: Record<MapSummary["phase"], number> = {
  LIVE: 0,
  AWAITING_RESULT: 1,
  PREMATCH: 2,
  UNKNOWN: 3,
  POSTMATCH: 4
};

function compareSeriesRouteMatches(left: MapSummary, right: MapSummary): number {
  const phaseDifference = phasePriority[left.phase] - phasePriority[right.phase];
  if (phaseDifference !== 0) return phaseDifference;
  const leftMap = left.map_number ?? 0;
  const rightMap = right.map_number ?? 0;
  return left.phase === "POSTMATCH" ? rightMap - leftMap : leftMap - rightMap;
}

export function aiAccessScope(
  session: AuthSessionState | undefined,
  match: Pick<MapSummary, "series_id" | "canonical_map_id" | "canonical_event_id" | "stage_key" | "phase"> | null
): AiAccessScope {
  if (!match) return null;
  if (session?.entitlements?.includes(AI_DECISIONS_ENTITLEMENT)) return "GLOBAL";

  const grants = session?.grants ?? [];
  if (
    match.canonical_event_id &&
    grants.some(
      (grant) =>
        grant.entitlement === AI_DECISIONS_ENTITLEMENT &&
        grant.scope_type === "EVENT" &&
        grant.scope_ref === match.canonical_event_id
    )
  ) {
    return "EVENT";
  }
  if (
    match.series_id &&
    grants.some(
      (grant) =>
        grant.entitlement === AI_DECISIONS_ENTITLEMENT &&
        grant.scope_type === "SERIES" &&
        grant.scope_ref === match.series_id
    )
  ) {
    return "SERIES";
  }
  if (
    match.canonical_map_id &&
    grants.some(
      (grant) =>
        grant.entitlement === AI_DECISIONS_ENTITLEMENT &&
        grant.scope_type === "MAP" &&
        grant.scope_ref === match.canonical_map_id
    )
  ) {
    return "MAP";
  }
  if (match.stage_key === "GROUP_STAGE") return "FREE";
  if (match.phase === "POSTMATCH") return "POSTMATCH";
  return null;
}
