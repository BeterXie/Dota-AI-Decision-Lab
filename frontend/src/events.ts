import type { MapSummary } from "./api";

export type EventStatus = "LIVE" | "UPCOMING" | "SETTLING" | "COMPLETED";

export interface EventSummary {
  name: string;
  matches: MapSummary[];
  status: EventStatus;
  seriesCount: number;
  teamCount: number;
  stages: string[];
  nextMatch: MapSummary | null;
  latestMatch: MapSummary | null;
  startsAt: string | null;
  endsAt: string | null;
}

export interface EventSeriesSummary {
  seriesId: string;
  phase: MapSummary["phase"];
  scheduledAt: string | null;
  round: string | null;
  bestOf: number | null;
  score: MapSummary["series_score"];
  teamA: MapSummary["team_a"];
  teamB: MapSummary["team_b"];
  representative: MapSummary;
  mapCount: number;
}

export function buildEventSummaries(matches: MapSummary[]): EventSummary[] {
  const grouped = new Map<string, MapSummary[]>();
  for (const match of matches) {
    const name = eventName(match);
    grouped.set(name, [...(grouped.get(name) ?? []), match]);
  }

  return Array.from(grouped.entries())
    .map(([name, eventMatches]) => buildEventSummary(name, eventMatches))
    .sort(compareEvents);
}

export function buildSeriesSummaries(event: EventSummary): EventSeriesSummary[] {
  const grouped = new Map<string, MapSummary[]>();
  for (const match of event.matches) {
    const key = match.series_id || match.id;
    grouped.set(key, [...(grouped.get(key) ?? []), match]);
  }

  return Array.from(grouped.entries())
    .map(([seriesId, matches]) => buildSeriesSummary(seriesId, matches))
    .sort((left, right) => {
      const phaseDelta = seriesPhaseRank(left.phase) - seriesPhaseRank(right.phase);
      if (phaseDelta !== 0) return phaseDelta;
      if (left.phase === "POSTMATCH") return compareDates(right.scheduledAt, left.scheduledAt);
      return compareDates(left.scheduledAt, right.scheduledAt);
    });
}

export function eventHref(name: string): string {
  return `/events/${encodeURIComponent(name)}`;
}

export function eventNameFromPath(pathname: string): string | null {
  if (pathname === "/events" || pathname === "/events/") return null;
  const prefix = "/events/";
  if (!pathname.startsWith(prefix)) return null;
  const segment = pathname.slice(prefix.length).split("/")[0];
  if (!segment) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

export function eventName(match: MapSummary): string {
  return match.tournament_name?.trim() || "Dota 2";
}

function buildEventSummary(name: string, matches: MapSummary[]): EventSummary {
  const seriesIds = new Set(matches.map((match) => match.series_id || match.id));
  const teams = new Set<string>();
  const stages = new Set<string>();
  for (const match of matches) {
    if (match.team_a?.id || match.team_a?.name) teams.add(match.team_a?.id || match.team_a?.name || "");
    if (match.team_b?.id || match.team_b?.name) teams.add(match.team_b?.id || match.team_b?.name || "");
    if (match.round?.trim()) stages.add(match.round.trim());
  }

  const upcoming = matches
    .filter((match) => match.phase === "PREMATCH" || match.phase === "UNKNOWN")
    .sort((left, right) => compareDates(left.scheduled_at, right.scheduled_at));
  const latest = [...matches].sort((left, right) => compareDates(right.scheduled_at, left.scheduled_at))[0] ?? null;
  const dates = matches
    .map((match) => match.scheduled_at)
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => Date.parse(left) - Date.parse(right));

  return {
    name,
    matches,
    status: eventStatus(matches),
    seriesCount: seriesIds.size,
    teamCount: teams.size,
    stages: Array.from(stages),
    nextMatch: upcoming[0] ?? null,
    latestMatch: latest,
    startsAt: dates[0] ?? null,
    endsAt: dates.at(-1) ?? null
  };
}

function buildSeriesSummary(seriesId: string, matches: MapSummary[]): EventSeriesSummary {
  const phase = seriesPhase(matches);
  const representative = pickRepresentative(matches, phase);
  const scoreRecord = [...matches]
    .filter((match) => match.series_score)
    .sort((left, right) => scoreTotal(right) - scoreTotal(left))[0];
  const scheduledAt = [...matches]
    .map((match) => match.scheduled_at)
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => Date.parse(left) - Date.parse(right))[0] ?? representative.scheduled_at;

  return {
    seriesId,
    phase,
    scheduledAt,
    round: representative.round,
    bestOf: representative.best_of ?? null,
    score: scoreRecord?.series_score ?? representative.series_score,
    teamA: representative.team_a,
    teamB: representative.team_b,
    representative,
    mapCount: matches.filter((match) => match.entity_type === "MAP").length || matches.length
  };
}

function eventStatus(matches: MapSummary[]): EventStatus {
  if (matches.some((match) => match.phase === "LIVE")) return "LIVE";
  if (matches.some((match) => match.phase === "PREMATCH" || match.phase === "UNKNOWN")) return "UPCOMING";
  if (matches.some((match) => match.phase === "AWAITING_RESULT")) return "SETTLING";
  return "COMPLETED";
}

function seriesPhase(matches: MapSummary[]): MapSummary["phase"] {
  if (matches.some((match) => match.phase === "LIVE")) return "LIVE";
  if (matches.some((match) => match.phase === "PREMATCH" || match.phase === "UNKNOWN")) return "PREMATCH";
  if (matches.some((match) => match.phase === "AWAITING_RESULT")) return "AWAITING_RESULT";
  return "POSTMATCH";
}

function pickRepresentative(matches: MapSummary[], phase: MapSummary["phase"]): MapSummary {
  const inPhase = matches.filter((match) => match.phase === phase);
  const candidates = inPhase.length > 0 ? inPhase : matches;
  return [...candidates].sort((left, right) => {
    if (phase === "POSTMATCH") return compareDates(right.scheduled_at, left.scheduled_at);
    return compareDates(left.scheduled_at, right.scheduled_at);
  })[0] ?? matches[0];
}

function scoreTotal(match: MapSummary): number {
  return (match.series_score?.team_a ?? 0) + (match.series_score?.team_b ?? 0);
}

function compareEvents(left: EventSummary, right: EventSummary): number {
  const statusDelta = eventStatusRank(left.status) - eventStatusRank(right.status);
  if (statusDelta !== 0) return statusDelta;
  const leftDate = left.nextMatch?.scheduled_at ?? left.latestMatch?.scheduled_at;
  const rightDate = right.nextMatch?.scheduled_at ?? right.latestMatch?.scheduled_at;
  return left.status === "COMPLETED"
    ? compareDates(rightDate, leftDate)
    : compareDates(leftDate, rightDate);
}

function eventStatusRank(status: EventStatus): number {
  if (status === "LIVE") return 0;
  if (status === "UPCOMING") return 1;
  if (status === "SETTLING") return 2;
  return 3;
}

function seriesPhaseRank(phase: MapSummary["phase"]): number {
  if (phase === "LIVE") return 0;
  if (phase === "PREMATCH" || phase === "UNKNOWN") return 1;
  if (phase === "AWAITING_RESULT") return 2;
  return 3;
}

function compareDates(left: string | null | undefined, right: string | null | undefined): number {
  if (!left && !right) return 0;
  if (!left) return 1;
  if (!right) return -1;
  return Date.parse(left) - Date.parse(right);
}
