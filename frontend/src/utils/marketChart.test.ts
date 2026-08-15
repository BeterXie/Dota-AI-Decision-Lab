import { expect, test } from "vitest";
import { MARKET_CHART_LEAD_SECONDS, marketChartZoomWindow } from "./marketChart";

test("defaults the odds chart to a short lead before the scheduled match", () => {
  const scheduled = Date.parse("2026-08-15T02:00:00Z");
  const timestamps = [
    scheduled - 12 * 60 * 60 * 1000,
    scheduled - 2 * 60 * 60 * 1000,
    scheduled - 10 * 60 * 1000,
    scheduled + 20 * 60 * 1000
  ];

  const zoom = marketChartZoomWindow(timestamps, "2026-08-15T02:00:00Z");

  expect(zoom.start).toBe(scheduled - MARKET_CHART_LEAD_SECONDS * 1000);
  expect(zoom.end).toBe(scheduled + 20 * 60 * 1000);
});

test("keeps the full range when the schedule is unknown", () => {
  const timestamps = [Date.parse("2026-08-14T14:00:00Z"), Date.parse("2026-08-14T18:00:00Z")];

  const zoom = marketChartZoomWindow(timestamps, null);

  expect(zoom.start).toBe(timestamps[0]);
  expect(zoom.end).toBe(timestamps[1]);
});

test("does not zoom past the earliest observation", () => {
  const scheduled = Date.parse("2026-08-15T02:00:00Z");
  const first = scheduled - 5 * 60 * 1000;
  const timestamps = [first, scheduled + 5 * 60 * 1000];

  const zoom = marketChartZoomWindow(timestamps, "2026-08-15T02:00:00Z");

  expect(zoom.start).toBe(first);
  expect(zoom.end).toBe(timestamps[1]);
});

test("does not apply a future-focused window before the data reaches the match window", () => {
  const scheduled = Date.parse("2026-08-15T10:00:00Z");
  const timestamps = [scheduled - 4 * 60 * 60 * 1000, scheduled - 2 * 60 * 60 * 1000];

  const zoom = marketChartZoomWindow(timestamps, "2026-08-15T10:00:00Z");

  expect(zoom.start).toBe(timestamps[0]);
  expect(zoom.end).toBe(timestamps[1]);
});
