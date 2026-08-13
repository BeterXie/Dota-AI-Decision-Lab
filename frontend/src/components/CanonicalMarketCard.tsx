import React from "react";
import type { MapDetail, MapSummary } from "../api";
import IntelligenceChart from "../Chart";
import { useI18n } from "../i18n";
import { formatOdds, primaryMarketPair } from "../utils/presentation";

const teamAColor = "#7C9CFF";
const teamBColor = "#9C82FF";

export function CanonicalMarketCard({ match }: { match: MapSummary | MapDetail }) {
  const { locale, t } = useI18n();
  const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
  const eligible = match.market_quality?.eligible === true;
  const teamA = match.team_a?.name ?? t("teamA");
  const teamB = match.team_b?.name ?? t("teamB");
  const timeline = "market_timeline" in match ? match.market_timeline : [];
  const dataA = pair ? timeline.filter((item) => item.odds_id === pair.teamA.odds_id).map((item) => [item.received_at, Number(item.price)]) : [];
  const dataB = pair ? timeline.filter((item) => item.odds_id === pair.teamB.odds_id).map((item) => [item.received_at, Number(item.price)]) : [];
  const age = pair ? Math.max(pair.teamA.age_seconds, pair.teamB.age_seconds) : null;
  const option = {
    animation: false,
    tooltip: { trigger: "axis" },
    grid: { left: 38, right: 12, top: 18, bottom: 26 },
    xAxis: { type: "time", axisLabel: { color: "#687386", fontSize: 10, hideOverlap: true } },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#687386", fontSize: 10 }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    series: [
      { name: teamA, type: "line", smooth: true, showSymbol: false, lineStyle: { width: 2, color: teamAColor }, data: dataA },
      { name: teamB, type: "line", smooth: true, showSymbol: false, lineStyle: { width: 2, color: teamBColor }, data: dataB }
    ]
  };

  return (
    <section className="analytics-card market-card player-market-card">
      <div className="player-section-heading compact"><div><span className="section-kicker">MARKET</span><h3>{t("primaryWinnerMarket")}</h3></div><span className={`player-status-pill ${eligible ? "ready" : "limited"}`}>{eligible ? "READY" : "LIMITED"}</span></div>
      {pair ? <>
        <div className="player-market-odds">
          <div><span>{teamA}</span><strong style={{ color: teamAColor }}>{formatOdds(pair.teamA.price)}</strong><small>{t("fair")} {eligible && pair.teamA.fair_probability != null ? pct(pair.teamA.fair_probability, locale) : "—"}</small></div>
          <div className="market-vs">VS</div>
          <div><span>{teamB}</span><strong style={{ color: teamBColor }}>{formatOdds(pair.teamB.price)}</strong><small>{t("fair")} {eligible && pair.teamB.fair_probability != null ? pct(pair.teamB.fair_probability, locale) : "—"}</small></div>
        </div>
        <div className="player-market-meta"><span>{t("freshness")} <b>{age == null ? "—" : `${age.toFixed(1)}s`}</b></span><span>{t("pairSkew")} <b>{match.market_quality?.pair_skew_seconds == null ? "—" : `${match.market_quality.pair_skew_seconds.toFixed(1)}s`}</b></span></div>
        <div className="player-market-chart">{dataA.length > 1 || dataB.length > 1 ? <IntelligenceChart option={option} /> : <span className="chart-empty">{t("waitingForOddsTrend")}</span>}</div>
      </> : <div className="empty-rail-msg">{t("marketUnavailable")}</div>}
    </section>
  );
}

function pct(value: number, locale: string) { return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value); }
