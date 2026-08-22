import type { MapSummary } from "./api";

export type MatchPhase = MapSummary["phase"];

export function isLivePhase(phase: MatchPhase): boolean {
  return phase === "LIVE" || phase === "LIVE_DATA_DELAYED";
}

export function isUpcomingPhase(phase: MatchPhase): boolean {
  return phase === "PREMATCH" || phase === "DELAYED_START" || phase === "UNKNOWN";
}

export function shouldPollMatchFrequently(phase: MatchPhase | undefined): boolean {
  return phase === "DELAYED_START" || (phase !== undefined && isLivePhase(phase));
}
