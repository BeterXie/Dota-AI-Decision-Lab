export const MARKET_CHART_LEAD_SECONDS = 15 * 60;

export interface ChartZoomWindow {
  start: number;
  end: number;
}

/**
 * Default viewport for the odds timeline chart.
 *
 * Pre-match observations can span many hours before a scheduled match and
 * would otherwise dominate the x-axis. When the schedule is known and the
 * data reaches (or passes) the match window, the default view starts a short
 * lead before the scheduled start; ECharts dataZoom still lets the user drag
 * back into the full pre-match history.
 */
export function marketChartZoomWindow(
  timestamps: number[],
  scheduledAt?: string | null
): ChartZoomWindow {
  const first = Math.min(...timestamps);
  const last = Math.max(...timestamps);
  const scheduled = scheduledAt ? Date.parse(scheduledAt) : Number.NaN;
  if (Number.isFinite(scheduled) && scheduled - MARKET_CHART_LEAD_SECONDS * 1000 < last) {
    return {
      start: Math.max(first, scheduled - MARKET_CHART_LEAD_SECONDS * 1000),
      end: last
    };
  }
  return { start: first, end: last };
}
