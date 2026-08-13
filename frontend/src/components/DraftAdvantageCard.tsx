import React from "react";
import type { MapDetail, MapSummary } from "../api";
import IntelligenceChart from "../Chart";
import { useI18n } from "../i18n";

interface DraftAdvantageCardProps {
  match: MapSummary | MapDetail;
  onViewDetails?: () => void;
}

export const DraftAdvantageCard: React.FC<DraftAdvantageCardProps> = ({ match, onViewDetails }) => {
  const { t } = useI18n();
  const curve = match.draft?.curve;

  const minutes = curve?.map((point) => point.minute) || [];
  const curveData = curve?.map((point) => {
    const edge = point.adjusted_radiant_edge ?? point.pure_radiant_edge;
    return edge == null ? null : edge;
  }) || [];

  const currentMinute = match.live?.game_time_seconds
    ? Math.floor(match.live.game_time_seconds / 60)
    : null;
  const currentPoint = currentMinute == null || !curve?.length
    ? null
    : curve.reduce((closest, point) =>
        Math.abs(point.minute - currentMinute) < Math.abs(closest.minute - currentMinute)
          ? point
          : closest
      );
  const currentValue = currentPoint?.adjusted_radiant_edge ?? currentPoint?.pure_radiant_edge;
  const knownPoints = (curve || []).filter((point) =>
    (point.adjusted_radiant_edge ?? point.pure_radiant_edge) != null
  );
  const peak = knownPoints.reduce<typeof knownPoints[number] | null>((best, point) => {
    const value = Math.abs(point.adjusted_radiant_edge ?? point.pure_radiant_edge ?? 0);
    const bestValue = Math.abs(best?.adjusted_radiant_edge ?? best?.pure_radiant_edge ?? 0);
    return best == null || value > bestValue ? point : best;
  }, null);
  const peakValue = peak?.adjusted_radiant_edge ?? peak?.pure_radiant_edge;

  const chartOption = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#171C24",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#F5F7FA", fontSize: 12 },
      formatter: (params: any) => {
        const item = params[0];
        return `Minute ${item.name}<br/>Radiant Edge: ${item.value > 0 ? "+" : ""}${item.value}%`;
      }
    },
    grid: {
      left: "8%",
      right: "5%",
      top: "15%",
      bottom: "18%"
    },
    xAxis: {
      type: "category",
      data: minutes.map((m) => `${m}m`),
      axisLine: { lineStyle: { color: "#687386" } },
      axisLabel: { color: "#9AA4B2", fontSize: 11 }
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: "#9AA4B2",
        fontSize: 11,
        formatter: (val: number) => `${val > 0 ? "+" : ""}${val}%`
      },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } }
    },
    series: [
      {
        name: "Radiant Edge",
        type: "line",
        smooth: true,
        data: curveData,
        lineStyle: { width: 2, color: "#41C98E" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(65, 201, 142, 0.3)" },
              { offset: 1, color: "rgba(65, 201, 142, 0.0)" }
            ]
          }
        },
        markPoint: {
          data: [
            { type: "max", name: "Peak", itemStyle: { color: "#E7B65A" } }
          ]
        }
      }
    ]
  };

  return (
    <div className="analytics-card draft-advantage-card">
      <div className="card-header">
        <span className="card-title">DRAFT ADVANTAGE (R.O.S.H.)</span>
        <span className="info-icon" title="Radiant vs Dire draft win probability advantage curve">
          ⓘ
        </span>
      </div>

      <div className="rosh-metrics-row">
        <div className="rosh-metric-item">
          <span className="lbl">Current Edge</span>
          <span className="val highlight-green">
            {currentValue == null ? "—" : `${currentValue >= 0 ? "+" : ""}${currentValue.toFixed(1)}%`}
          </span>
        </div>
        <div className="rosh-metric-item">
          <span className="lbl">Peak Advantage</span>
          <span className="val">
            {peakValue == null ? "—" : `${peakValue >= 0 ? "+" : ""}${peakValue.toFixed(1)}% @ ${peak?.minute}m`}
          </span>
        </div>
        <div className="rosh-metric-item">
          <span className="lbl">Cross-over</span>
          <span className="val">—</span>
        </div>
      </div>

      <div className="rosh-chart-container">
        {curveData.length ? <IntelligenceChart option={chartOption} /> : <span>{t("noRoshCurve")}</span>}
      </div>

      {onViewDetails && (
        <div className="card-footer-action">
          <button className="text-action-btn" onClick={onViewDetails}>
            VIEW DETAILS →
          </button>
        </div>
      )}
    </div>
  );
};
