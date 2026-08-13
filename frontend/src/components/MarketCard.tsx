import React from "react";
import type { MapDetail, MapSummary } from "../api";
import IntelligenceChart from "../Chart";
import { useI18n } from "../i18n";

interface MarketCardProps {
  match: MapSummary | MapDetail;
}

export const MarketCard: React.FC<MarketCardProps> = ({ match }) => {
  const { t } = useI18n();
  const teamA = match.team_a?.name || t("unknownTeam");
  const teamB = match.team_b?.name || t("unknownTeam");

  const oddsANumber = match.market?.[0]?.price ? Number(match.market[0].price) : null;
  const oddsBNumber = match.market?.[1]?.price ? Number(match.market[1].price) : null;
  const oddsA = oddsANumber?.toFixed(2) ?? "—";
  const oddsB = oddsBNumber?.toFixed(2) ?? "—";
  const ageSeconds = match.market?.[0]?.age_seconds;

  // Calculate no-vig
  const pA = oddsANumber ? 1 / oddsANumber : null;
  const pB = oddsBNumber ? 1 / oddsBNumber : null;
  const sumP = pA != null && pB != null ? pA + pB : null;
  const noVigA = pA != null && sumP ? Math.round((pA / sumP) * 100) : null;
  const noVigB = noVigA != null ? 100 - noVigA : null;

  // Chart data
  const timeline = "market_timeline" in match ? match.market_timeline : [];
  const byOddsId = new Map<number, typeof timeline>();
  timeline.forEach((item) => byOddsId.set(item.odds_id, [...(byOddsId.get(item.odds_id) || []), item]));
  const series = [...byOddsId.values()].slice(0, 2);
  const times = series[0]?.map((item) => new Date(item.received_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })) || [];

  const chartOption = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#171C24",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#F5F7FA", fontSize: 12 }
    },
    grid: {
      left: "8%",
      right: "5%",
      top: "15%",
      bottom: "18%"
    },
    xAxis: {
      type: "category",
      data: times,
      axisLine: { lineStyle: { color: "#687386" } },
      axisLabel: { color: "#9AA4B2", fontSize: 11 }
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
      axisLabel: { color: "#9AA4B2", fontSize: 11 }
    },
    series: [
      {
        name: teamA,
        type: "line",
        smooth: true,
        data: series[0]?.map((item) => Number(item.price)) || [],
        itemStyle: { color: "#41C98E" },
        lineStyle: { width: 2 }
      },
      {
        name: teamB,
        type: "line",
        smooth: true,
        data: series[1]?.map((item) => Number(item.price)) || [],
        itemStyle: { color: "#F06A72" },
        lineStyle: { width: 2 }
      }
    ]
  };

  return (
    <div className="analytics-card market-card">
      <div className="card-header">
        <span className="card-title">MARKET ODDS</span>
        <span className="info-icon" title="RayBet live market odds & historical timeline">
          ⓘ
        </span>
      </div>

      <div className="odds-summary-row">
        <div className="odds-team-box radiant">
          <span className="odds-val">{oddsA}</span>
          <span className="odds-lbl">{teamA}</span>
        </div>
        <div className="odds-team-box dire">
          <span className="odds-val">{oddsB}</span>
          <span className="odds-lbl">{teamB}</span>
        </div>
      </div>

      <div className="odds-sub-meta">
        <span className="no-vig-info">
          no-vig: {noVigA == null ? "—" : `${noVigA}% / ${noVigB}%`}
        </span>
        <span className="fresh-info">
          {ageSeconds == null ? t("notObserved") : `${t("updatedAt")} ${Math.round(ageSeconds)}s`}
        </span>
      </div>

      <div className="market-chart-container">
        {times.length > 1 ? <IntelligenceChart option={chartOption} /> : <span>{t("waitingForOddsTrend")}</span>}
      </div>
    </div>
  );
};
