import type { MapSummary } from "./api";
import type { AuthSessionState } from "./authApi";

export type AiAccessScope = "GLOBAL" | "SERIES" | "MAP" | null;

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
  return (
    matches.find((match) => match.canonical_map_id === routeId) ??
    matches.find((match) => match.id === routeId) ??
    null
  );
}

export function aiAccessScope(
  session: AuthSessionState | undefined,
  match: Pick<MapSummary, "series_id" | "canonical_map_id"> | null
): AiAccessScope {
  if (session?.entitlements?.includes(AI_DECISIONS_ENTITLEMENT)) return "GLOBAL";
  if (!match) return null;

  const grants = session?.grants ?? [];
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
  return null;
}
