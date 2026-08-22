import { describe, expect, it } from "vitest";
import type { MapSummary } from "./api";
import {
  buildEventSummaries,
  buildSeriesSummaries,
  eventHref,
  eventName,
  eventNameFromPath,
  eventSlug,
  isSeriesComplete,
  isSeriesOngoing
} from "./events";

function match(overrides: Partial<MapSummary>): MapSummary {
  return {
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "PREMATCH",
    id: "map-1",
    series_id: "series-1",
    canonical_map_id: "map-1",
    map_number: 1,
    valve_match_id: null,
    scheduled_at: "2026-08-18T12:00:00Z",
    provider_match_id: null,
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
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
    decisions: [],
    ...overrides
  };
}

describe("event aggregation", () => {
  it("groups map records into events and counts unique series", () => {
    const events = buildEventSummaries([
      match({ id: "map-1", series_id: "series-a", phase: "LIVE", map_number: 1 }),
      match({ id: "map-2", series_id: "series-a", phase: "PREMATCH", map_number: 2 }),
      match({ id: "map-3", series_id: "series-b", phase: "PREMATCH", map_number: 1 })
    ]);

    expect(events).toHaveLength(1);
    expect(events[0].status).toBe("LIVE");
    expect(events[0].seriesCount).toBe(2);
    expect(events[0].teamCount).toBe(2);
    expect(events[0].nextMatch?.id).toBe("map-2");
  });

  it("sorts active events before completed events", () => {
    const events = buildEventSummaries([
      match({ id: "done", tournament_name: "Finished Cup", phase: "POSTMATCH", scheduled_at: "2026-08-17T10:00:00Z" }),
      match({ id: "next", tournament_name: "Future Cup", phase: "PREMATCH", scheduled_at: "2026-08-19T10:00:00Z" })
    ]);

    expect(events.map((event) => event.name)).toEqual(["Future Cup", "Finished Cup"]);
  });

  it("keeps delayed starts upcoming and delayed live data in the live group", () => {
    const [delayedStartEvent] = buildEventSummaries([
      match({ phase: "DELAYED_START" }),
    ]);
    const [delayedLiveEvent] = buildEventSummaries([
      match({ phase: "LIVE_DATA_DELAYED" }),
    ]);

    expect(delayedStartEvent.status).toBe("UPCOMING");
    expect(delayedStartEvent.nextMatch?.phase).toBe("DELAYED_START");
    expect(delayedLiveEvent.status).toBe("LIVE");
    expect(buildSeriesSummaries(delayedLiveEvent)[0].phase).toBe("LIVE_DATA_DELAYED");
  });

  it("keeps an event ongoing between completed and upcoming series", () => {
    const [event] = buildEventSummaries([
      match({ id: "done", series_id: "series-done", phase: "POSTMATCH" }),
      match({ id: "next", series_id: "series-next", phase: "PREMATCH" })
    ]);

    expect(event.status).toBe("LIVE");
    expect(event.nextMatch?.id).toBe("next");
  });

  it("keeps only confirmed competition stages and never treats BO labels as stages", () => {
    const [event] = buildEventSummaries([
      match({ id: "map-1", series_id: "series-a", round: "BO3" }),
      match({ id: "map-2", series_id: "series-b", round: "schedule" }),
      match({ id: "map-3", series_id: "series-c", round: "小组赛" })
    ]);

    expect(event.stages).toEqual(["小组赛"]);
  });

  it("collapses multiple maps into one series row and keeps the latest score", () => {
    const [event] = buildEventSummaries([
      match({ id: "map-1", series_id: "series-a", phase: "POSTMATCH", series_score: { team_a: 1, team_b: 0 } }),
      match({ id: "map-2", series_id: "series-a", phase: "POSTMATCH", map_number: 2, series_score: { team_a: 2, team_b: 0 } })
    ]);
    const series = buildSeriesSummaries(event);

    expect(series).toHaveLength(1);
    expect(series[0].mapCount).toBe(2);
    expect(series[0].score).toEqual({ team_a: 2, team_b: 0 });
    expect(series[0].phase).toBe("POSTMATCH");
  });

  it("keeps a BO3 ongoing after the first confirmed map", () => {
    const [event] = buildEventSummaries([
      match({
        id: "map-1",
        phase: "POSTMATCH",
        best_of: 3,
        series_score: { team_a: 0, team_b: 1 }
      })
    ]);
    const [series] = buildSeriesSummaries(event);

    expect(isSeriesComplete(match({ best_of: 3, series_score: { team_a: 0, team_b: 1 } }))).toBe(false);
    expect(isSeriesOngoing(match({ phase: "POSTMATCH", best_of: 3, series_score: { team_a: 0, team_b: 1 } }))).toBe(true);
    expect(series.phase).toBe("LIVE");
    expect(event.status).toBe("LIVE");
  });

  it("ends a BO3 only after a team reaches the required wins", () => {
    expect(isSeriesComplete(match({ best_of: 3, series_score: { team_a: 2, team_b: 0 } }))).toBe(true);
    expect(isSeriesOngoing(match({ phase: "POSTMATCH", best_of: 3, series_score: { team_a: 2, team_b: 0 } }))).toBe(false);
  });

  it("keeps a partial score in settling state when one map awaits confirmation", () => {
    const [event] = buildEventSummaries([
      match({ id: "map-1", series_id: "series-a", phase: "POSTMATCH", series_score: { team_a: 1, team_b: 0 } }),
      match({ id: "map-2", series_id: "series-a", phase: "AWAITING_RESULT", map_number: 2, series_score: { team_a: 1, team_b: 0 } })
    ]);
    const [series] = buildSeriesSummaries(event);

    expect(series.phase).toBe("AWAITING_RESULT");
    expect(series.score).toEqual({ team_a: 1, team_b: 0 });
  });

  it("uses readable ASCII slugs for public event URLs", () => {
    expect(eventName(match({}))).toBe("The International 2026");
    expect(eventSlug("TI15 国际邀请赛")).toBe("the-international-2026");
    expect(eventHref("TI15 国际邀请赛")).toBe("/events/the-international-2026");
    expect(eventSlug("DreamLeague S24")).toBe("dreamleague-s24");
  });

  it("keeps encoded event-name URLs readable", () => {
    const name = "The International 2026";
    expect(eventNameFromPath(`/events/${encodeURIComponent(name)}`)).toBe(name);
    expect(eventNameFromPath(eventHref(name))).toBe("the-international-2026");
  });
});
