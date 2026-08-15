import type { MapSummary, MarketObservation } from "../api";

export type MatchDisplayPhase = "LIVE" | "UPCOMING" | "AWAITING_RESULT" | "POSTMATCH" | "TRACKED";

export function getMatchDisplayPhase(match: MapSummary): MatchDisplayPhase {
  if (match.phase === "LIVE") return "LIVE";
  if (match.phase === "PREMATCH") return "UPCOMING";
  if (match.phase === "AWAITING_RESULT") return "AWAITING_RESULT";
  if (match.phase === "POSTMATCH") return "POSTMATCH";

  // Backward-compatible fallback for cached fixtures / transitional API payloads.
  if (match.live?.game_time_seconds != null || match.latest_snapshot?.mode?.startsWith("LIVE")) {
    return "LIVE";
  }
  if (match.scheduled_at) {
    const scheduledAt = Date.parse(match.scheduled_at);
    if (Number.isFinite(scheduledAt) && scheduledAt > Date.now()) return "UPCOMING";
  }
  return "TRACKED";
}

export interface PrimaryMarketPair {
  teamA: MarketObservation;
  teamB: MarketObservation;
  stage: string | null;
}

export function primaryMarketPair(
  markets: MarketObservation[],
  teamAId: string | null | undefined,
  teamBId: string | null | undefined
): PrimaryMarketPair | null {
  if (!teamAId || !teamBId) return null;
  const groups = new Map<string, MarketObservation[]>();
  for (const item of markets) {
    if (item.selection_team_id !== teamAId && item.selection_team_id !== teamBId) continue;
    const key = `${item.market_type ?? ""}::${item.match_stage ?? ""}`;
    const group = groups.get(key) ?? [];
    group.push(item);
    groups.set(key, group);
  }
  const candidates = [...groups.entries()]
    .map(([key, group]) => ({ key, teamA: latestForTeam(group, teamAId), teamB: latestForTeam(group, teamBId) }))
    .filter((candidate): candidate is { key: string; teamA: MarketObservation; teamB: MarketObservation } => Boolean(candidate.teamA && candidate.teamB))
    .sort((left, right) => marketPriority(left.key) - marketPriority(right.key));
  const selected = candidates[0];
  return selected
    ? {
        teamA: selected.teamA,
        teamB: selected.teamB,
        stage: selected.teamA.match_stage ?? selected.teamB.match_stage
      }
    : null;
}

function latestForTeam(items: MarketObservation[], teamId: string): MarketObservation | null {
  return items
    .filter((item) => item.selection_team_id === teamId)
    .sort((left, right) => Date.parse(right.received_at) - Date.parse(left.received_at))[0] ?? null;
}

function marketPriority(key: string): number {
  const normalized = key.toLowerCase();
  if (!normalized.includes("winner")) return 10;
  if (normalized.includes("map") || normalized.includes("round")) return 0;
  if (normalized.includes("final") || normalized.includes("full time")) return 2;
  return 1;
}

export function formatOdds(value: number | string | null | undefined): string {
  if (value == null) return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(2) : "—";
}

export function marketStageDisplayLabel(
  mapNumber: number | null,
  bestOf: number | null,
  stage: string | null,
  locale: string
): string {
  const zh = locale === "zh-CN";
  if (stage?.toLowerCase() === "final" && mapNumber != null && bestOf != null && mapNumber === bestOf) {
    return zh
      ? `第${mapNumber}局（决胜局）· RayBet 将本局并入 BO3 胜者盘`
      : `Map ${mapNumber} (decider) · merged into BO3 winner market`;
  }
  const map = stage?.match(/^r?(\d+)$/i);
  if (map) {
    return zh ? `第${map[1]}局` : `Map ${map[1]}`;
  }
  return stage ?? (zh ? "未知盘口" : "Unknown market stage");
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}
