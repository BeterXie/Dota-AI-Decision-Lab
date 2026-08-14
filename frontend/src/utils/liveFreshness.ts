import type { MapDetail, MapSummary } from "../api";

export const LIVE_BASIC_FIELDS = [
  "game_time_seconds",
  "radiant_kills",
  "dire_kills",
  "radiant_nw_lead"
] as const;

export type LiveBasicField = (typeof LIVE_BASIC_FIELDS)[number];

export interface DecisionLiveFreshness {
  complete: boolean | null;
  effectiveAgeSeconds: number | null;
  agesSeconds: Partial<Record<LiveBasicField, number>>;
  observedAt: Partial<Record<LiveBasicField, string>>;
  source: "SNAPSHOT_FIELD_EVIDENCE" | "LIVE_STATE_FALLBACK";
}

export function resolveDecisionLiveFreshness(
  match: MapSummary | MapDetail,
  fallbackNowMs: number = Date.now()
): DecisionLiveFreshness {
  const raw = isMapDetail(match)
    ? match.snapshot_payload?.quality?.live_field_freshness
    : undefined;
  if (!isRecord(raw)) {
    return {
      complete: null,
      effectiveAgeSeconds: match.live?.effective_state_age_seconds ?? null,
      agesSeconds: {},
      observedAt: {},
      source: "LIVE_STATE_FALLBACK"
    };
  }

  const rawAges = isRecord(raw.ages_seconds) ? raw.ages_seconds : {};
  const rawObservedAt = isRecord(raw.observed_at) ? raw.observed_at : {};
  const referenceNowMs = serverReferenceTimeMs(match, fallbackNowMs);
  const agesSeconds: Partial<Record<LiveBasicField, number>> = {};
  const observedAt: Partial<Record<LiveBasicField, string>> = {};

  for (const field of LIVE_BASIC_FIELDS) {
    const observed = rawObservedAt[field];
    if (typeof observed === "string") {
      observedAt[field] = observed;
      const observedMs = Date.parse(observed);
      if (Number.isFinite(observedMs)) {
        agesSeconds[field] = Math.max(0, (referenceNowMs - observedMs) / 1000);
        continue;
      }
    }
    const storedAge = rawAges[field];
    if (typeof storedAge === "number" && Number.isFinite(storedAge)) {
      agesSeconds[field] = storedAge;
    }
  }

  const allRequiredFieldsObserved = LIVE_BASIC_FIELDS.every(
    (field) => agesSeconds[field] != null
  );
  const declaredComplete = typeof raw.complete === "boolean" ? raw.complete : null;
  const complete = declaredComplete === false
    ? false
    : declaredComplete === true
      ? allRequiredFieldsObserved
      : allRequiredFieldsObserved
        ? true
        : null;
  const effectiveAgeSeconds = complete
    ? Math.max(...LIVE_BASIC_FIELDS.map((field) => agesSeconds[field] ?? 0))
    : null;

  return {
    complete,
    effectiveAgeSeconds,
    agesSeconds,
    observedAt,
    source: "SNAPSHOT_FIELD_EVIDENCE"
  };
}

function serverReferenceTimeMs(match: MapSummary | MapDetail, fallbackNowMs: number): number {
  const lastMessageAt = match.live?.last_message_received_at;
  const messageAgeSeconds = match.live?.message_age_seconds;
  if (lastMessageAt && messageAgeSeconds != null && Number.isFinite(messageAgeSeconds)) {
    const lastMessageMs = Date.parse(lastMessageAt);
    if (Number.isFinite(lastMessageMs)) {
      return lastMessageMs + Math.max(0, messageAgeSeconds) * 1000;
    }
  }
  return fallbackNowMs;
}

function isMapDetail(match: MapSummary | MapDetail): match is MapDetail {
  return "snapshot_payload" in match;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
