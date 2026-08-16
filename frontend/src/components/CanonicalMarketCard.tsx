import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { useI18n } from "../i18n";
import { marketChartZoomWindow } from "../utils/marketChart";
import { formatOdds, getMatchDisplayPhase, marketStageDisplayLabel, primaryMarketPair } from "../utils/presentation";

const IntelligenceChart = React.lazy(() => import("../Chart"));
const teamAColor = "#7C9CFF";
const teamBColor = "#9C82FF";

export function CanonicalMarketCard({ match }: { match: MapSummary | MapDetail }) {
  const { locale, t } = useI18n();
  const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
  const phase = getMatchDisplayPhase(match);
  const marketClosed = phase === "POSTMATCH" || phase === "AWAITING_RESULT";
  const eligible = marketClosed ? false : match.market_quality?.eligible === true;
  const statusClass = marketClosed ? "closed" : eligible ? "ready" : "limited";
  const statusLabel = marketClosed ? t("marketClosed") : eligible ? "READY" : "LIMITED";
  const closedNote = phase === "POSTMATCH" ? t("marketClosedPostmatch") : t("marketClosedAwaitingResult");
  const teamA = match.team_a?.name ?? t("teamA");
  const teamB = match.team_b?.name ?? t("teamB");
  const fairA = eligible
    ? match.current_market_view?.team_a?.fair_probability ?? pair?.teamA.fair_probability ?? null
    : null;
  const fairB = eligible
    ? match.current_market_view?.team_b?.fair_probability ?? pair?.teamB.fair_probability ?? null
    : null;
  const timeline = "market_timeline" in match ? match.market_timeline : [];
  const dataA = pair ? timeline.filter((item) => item.odds_id === pair.teamA.odds_id).map((item) => [item.received_at, Number(item.price)]) : [];
  const dataB = pair ? timeline.filter((item) => item.odds_id === pair.teamB.odds_id).map((item) => [item.received_at, Number(item.price)]) : [];
  const timestamps = [...dataA, ...dataB].map((item) => Date.parse(String(item[0]))).filter(Number.isFinite);
  const zoom = timestamps.length ? marketChartZoomWindow(timestamps, match.scheduled_at) : null;
  const age = pair ? Math.max(pair.teamA.age_seconds, pair.teamB.age_seconds) : null;
  const option = {
    animation: false,
    tooltip: { trigger: "axis" },
    grid: { left: 38, right: 12, top: 18, bottom: 40 },
    xAxis: { type: "time", axisLabel: { color: "#687386", fontSize: 10, hideOverlap: true } },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#687386", fontSize: 10 }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    dataZoom: zoom ? [
      { type: "inside", xAxisIndex: 0, startValue: zoom.start, endValue: zoom.end },
      { type: "slider", xAxisIndex: 0, height: 14, bottom: 2, startValue: zoom.start, endValue: zoom.end, borderColor: "rgba(255,255,255,.08)", backgroundColor: "rgba(255,255,255,.03)", fillerColor: "rgba(124,156,255,.12)", handleStyle: { color: "#7C9CFF" }, textStyle: { color: "#687386", fontSize: 9 } }
    ] : [],
    series: [
      { name: teamA, type: "line", smooth: true, showSymbol: false, lineStyle: { width: 2, color: teamAColor }, data: dataA },
      { name: teamB, type: "line", smooth: true, showSymbol: false, lineStyle: { width: 2, color: teamBColor }, data: dataB }
    ]
  };

  return (
    <section className={`analytics-card market-card player-market-card${marketClosed ? " market-closed" : ""}`}>
      <div className="player-section-heading compact"><div><span className="section-kicker">MARKET</span><h3>{t("primaryWinnerMarket")}</h3></div><span className={`player-status-pill ${statusClass}`}>{statusLabel}</span></div>
      {marketClosed ? <div className="player-market-closed-note">{closedNote}</div> : null}
      {pair ? <>
        <div className="player-market-odds">
          <div><span>{teamA}</span><strong style={{ color: teamAColor }}>{formatOdds(pair.teamA.price)}</strong><small>{t("fair")} {fairA != null ? pct(fairA, locale) : "—"}</small></div>
          <div className="market-vs">VS</div>
          <div><span>{teamB}</span><strong style={{ color: teamBColor }}>{formatOdds(pair.teamB.price)}</strong><small>{t("fair")} {fairB != null ? pct(fairB, locale) : "—"}</small></div>
        </div>
        <div className="player-market-meta">
          <span>{t("marketStage")} <b>{marketStageDisplayLabel(match.map_number ?? null, match.best_of ?? null, pair.stage, locale)}</b></span>
          <span>{t("freshness")} <b>{age == null ? "—" : `${age.toFixed(1)}s`}</b></span>
          <span>{t("pairSkew")} <b>{match.market_quality?.pair_skew_seconds == null ? "—" : `${match.market_quality.pair_skew_seconds.toFixed(1)}s`}</b></span>
        </div>
        <div className="player-market-chart">
          {dataA.length > 1 || dataB.length > 1 ? (
            <React.Suspense fallback={<span className="chart-empty">{t("waitingForOddsTrend")}</span>}>
              <IntelligenceChart option={option} />
            </React.Suspense>
          ) : <span className="chart-empty">{t("waitingForOddsTrend")}</span>}
        </div>
      </> : <div className="empty-rail-msg">{t("marketUnavailable")}</div>}
    </section>
  );
}

function pct(value: number, locale: string) { return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value); }
