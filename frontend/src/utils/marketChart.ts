export const MARKET_CHART_LEAD_SECONDS = 15 * 60;

const MARKET_CHART_OUTLIER_MAX_GAP_SECONDS = 30;
const MARKET_CHART_OUTLIER_MAX_DURATION_SECONDS = 30;
const MARKET_CHART_OUTLIER_BASELINE_RATIO = 1.25;
const MARKET_CHART_OUTLIER_SPIKE_RATIO = 3;

type MarketChartObservation = {
  odds_id: number;
  price: number | string;
  received_at: string;
};

type TimedMarketPoint<T extends MarketChartObservation> = {
  item: T;
  index: number;
  timestamp: number;
  price: number;
};

/**
 * Removes only short-lived display anomalies. Raw market observations remain
 * available through the API and are intentionally not changed here.
 */
export function filterMarketChartOutliers<T extends MarketChartObservation>(observations: T[]): T[] {
  const excluded = new Set<T>();
  const pointsByOddsId = new Map<number, TimedMarketPoint<T>[]>();

  observations.forEach((item, index) => {
    const timestamp = Date.parse(item.received_at);
    const price = Number(item.price);
    if (!Number.isFinite(timestamp) || !Number.isFinite(price) || price <= 0) return;

    const points = pointsByOddsId.get(item.odds_id) ?? [];
    points.push({ item, index, timestamp, price });
    pointsByOddsId.set(item.odds_id, points);
  });

  for (const points of pointsByOddsId.values()) {
    points.sort((left, right) => left.timestamp - right.timestamp || left.index - right.index);

    let start = 1;
    while (start < points.length - 1) {
      const before = points[start - 1];
      const firstSpike = points[start];
      if (
        firstSpike.timestamp - before.timestamp > MARKET_CHART_OUTLIER_MAX_GAP_SECONDS * 1000 ||
        priceRatio(firstSpike.price, before.price) < MARKET_CHART_OUTLIER_SPIKE_RATIO
      ) {
        start += 1;
        continue;
      }

      let end = start;
      while (end + 1 < points.length) {
        const next = points[end + 1];
        if (
          next.timestamp - points[end].timestamp > MARKET_CHART_OUTLIER_MAX_GAP_SECONDS * 1000 ||
          priceRatio(next.price, before.price) < MARKET_CHART_OUTLIER_SPIKE_RATIO
        ) {
          break;
        }
        end += 1;
      }

      const after = points[end + 1];
      const boundedByNeighbors =
        after !== undefined &&
        after.timestamp - points[end].timestamp <= MARKET_CHART_OUTLIER_MAX_GAP_SECONDS * 1000;
      const shortLived =
        after !== undefined &&
        after.timestamp - before.timestamp <= MARKET_CHART_OUTLIER_MAX_DURATION_SECONDS * 1000;
      const neighborsAgree = after !== undefined && priceRatio(before.price, after.price) <= MARKET_CHART_OUTLIER_BASELINE_RATIO;
      const everyPointIsAnOutlier =
        after !== undefined &&
        points.slice(start, end + 1).every(
          (point) =>
            priceRatio(point.price, before.price) >= MARKET_CHART_OUTLIER_SPIKE_RATIO &&
            priceRatio(point.price, after.price) >= MARKET_CHART_OUTLIER_SPIKE_RATIO
        );

      if (boundedByNeighbors && shortLived && neighborsAgree && everyPointIsAnOutlier) {
        for (let index = start; index <= end; index += 1) excluded.add(points[index].item);
      }

      start = end + 1;
    }
  }

  return observations.filter((item) => !excluded.has(item));
}

function priceRatio(left: number, right: number): number {
  const high = Math.max(left, right);
  const low = Math.min(left, right);
  return low > 0 ? high / low : Number.POSITIVE_INFINITY;
}

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
