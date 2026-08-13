import React from "react";
import type { DraftPoint, MapDetail, MapSummary } from "../api";
import IntelligenceChart from "../Chart";
import { useI18n } from "../i18n";

export function PlayerDraftAdvantageCard({ match, onViewDetails }: { match: MapSummary | MapDetail; onViewDetails?: () => void }) {
  const { locale, t } = useI18n();
  const curve = match.draft?.curve ?? [];
  const features = match.draft?.features ?? {};
  const current = featureNumber(features, "current_edge") ?? nearestCurrentEdge(curve, match.live?.game_time_seconds);
  const next5 = featureNumber(features, "next_5m_edge");
  const peak = featureNumber(features, "peak_edge") ?? peakEdge(curve)?.edge ?? null;
  const peakMinute = featureNumber(features, "peak_minute") ?? peakEdge(curve)?.minute ?? null;
  const crossMinute = featureNumber(features, "cross_over_minute");
  const currentSide = edgeSide(current);
  const nextSide = edgeSide(next5);
  const peakSide = edgeSide(peak);
  const afterCross = crossMinute == null ? "even" : edgeSide(edgeAfterMinute(curve, crossMinute));
  const adjusted = curve.map((point) => [point.minute, point.adjusted_radiant_edge]);
  const pure = curve.map((point) => [point.minute, point.pure_radiant_edge]);
  const maxAbs = Math.max(5, ...curve.flatMap((point) => [Math.abs(point.adjusted_radiant_edge ?? 0), Math.abs(point.pure_radiant_edge ?? 0)]));
  const bound = Math.ceil(maxAbs * 1.25);

  const chartOption = {
    animation: false,
    tooltip: {
      trigger: "axis",
      formatter: (params: Array<{ seriesName: string; value: [number, number | null] }>) => params.map((item) => {
        const value = item.value?.[1];
        return `${item.seriesName}: ${value == null ? "—" : edgeText(value, locale)}`;
      }).join("<br/>")
    },
    legend: { top: 0, right: 0, textStyle: { color: "#9AA4B2", fontSize: 10 }, data: [t("pure"), t("playerAdjusted")] },
    grid: { left: 48, right: 16, top: 34, bottom: 28 },
    xAxis: { type: "value", min: 20, max: 60, axisLabel: { color: "#687386", fontSize: 10, formatter: "{value}m" }, axisLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
    yAxis: { type: "value", min: -bound, max: bound, axisLabel: { color: "#687386", fontSize: 10, formatter: (value: number) => `${value > 0 ? "+" : ""}${value}pp` }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    series: [
      { name: t("pure"), type: "line", smooth: true, showSymbol: false, data: pure, lineStyle: { width: 2, color: "#7C9CFF", opacity: 0.75 } },
      { name: t("playerAdjusted"), type: "line", smooth: true, showSymbol: false, data: adjusted, lineStyle: { width: 3, color: "#9C82FF" }, areaStyle: { opacity: 0.05 }, markLine: { silent: true, symbol: "none", label: { formatter: locale === "zh-CN" ? "均势" : "EVEN", color: "#687386", fontSize: 9 }, lineStyle: { color: "rgba(255,255,255,.16)", type: "dashed" }, data: [{ yAxis: 0 }] } }
    ]
  };

  return (
    <section className="analytics-card draft-advantage-card player-rosh-card">
      <div className="player-section-heading compact">
        <div><span className="section-kicker">DRAFT INTELLIGENCE</span><h3>R.O.S.H. {locale === "zh-CN" ? "阵容优势" : "Draft Advantage"}</h3></div>
        <span className={`player-status-pill ${match.draft?.complete ? "ready" : "limited"}`}>{match.draft?.complete ? "READY" : "PARTIAL"}</span>
      </div>

      <div className={`rosh-verdict ${currentSide}`}>
        <div>
          <span>{locale === "zh-CN" ? "当前阵容倾向" : "Current draft favors"}</span>
          <strong>{current == null ? "—" : currentSide === "even" ? (locale === "zh-CN" ? "双方接近均势" : "Near even") : `${sideLabel(currentSide, locale)} ${locale === "zh-CN" ? "占优" : "advantage"}`}</strong>
        </div>
        <b>{current == null ? "—" : currentSide === "even" ? "0.0pp" : `+${Math.abs(current).toFixed(1)}pp`}</b>
        <small>{locale === "zh-CN"
          ? "R.O.S.H. 表示天辉相对夜魇的阵容优势：正值偏天辉，负值偏夜魇。Team A / Team B 与本局阵营不会在缺少显式映射时强行等同。"
          : "R.O.S.H. is Radiant-minus-Dire draft edge: positive favors Radiant, negative favors Dire. Team A/B are not forced onto map sides without explicit side identity."}</small>
      </div>

      <div className="rosh-direction-metrics">
        <DirectionalMetric label={t("currentEdge")} value={current} side={currentSide} locale={locale} />
        <DirectionalMetric label={t("next5m")} value={next5} side={nextSide} locale={locale} />
        <DirectionalMetric label={t("peakEdge")} value={peak} side={peakSide} locale={locale} suffix={peakMinute == null ? "" : ` @ ${peakMinute.toFixed(0)}m`} />
        <div className="rosh-direction-metric crossover"><span>{locale === "zh-CN" ? "优势翻转" : "Cross-over"}</span><strong>{crossMinute == null ? (locale === "zh-CN" ? "未发现" : "None") : `${crossMinute.toFixed(0)}m → ${sideLabel(afterCross, locale)}`}</strong></div>
      </div>

      <div className="rosh-chart-shell">
        <span className="rosh-zone-label radiant">↑ {locale === "zh-CN" ? "天辉优势区" : "Radiant advantage"}</span>
        <span className="rosh-zone-label dire">↓ {locale === "zh-CN" ? "夜魇优势区" : "Dire advantage"}</span>
        <div className="rosh-chart-container">{curve.length ? <IntelligenceChart option={chartOption} /> : <span className="chart-empty">{t("noRoshCurve")}</span>}</div>
      </div>

      {onViewDetails && <div className="card-footer-action"><button className="text-action-btn" onClick={onViewDetails}>{t("viewDetails")} →</button></div>}
    </section>
  );
}

function DirectionalMetric({ label, value, side, locale, suffix = "" }: { label: string; value: number | null; side: EdgeSide; locale: string; suffix?: string }) {
  return <div className={`rosh-direction-metric ${side}`}><span>{label}</span><strong>{value == null ? "—" : side === "even" ? (locale === "zh-CN" ? "均势" : "Even") : `${sideLabel(side, locale)} +${Math.abs(value).toFixed(1)}pp${suffix}`}</strong></div>;
}

type EdgeSide = "radiant" | "dire" | "even";
function edgeSide(value: number | null): EdgeSide { return value == null || Math.abs(value) < 0.05 ? "even" : value > 0 ? "radiant" : "dire"; }
function sideLabel(side: EdgeSide, locale: string): string {
  if (side === "radiant") return locale === "zh-CN" ? "天辉" : "Radiant";
  if (side === "dire") return locale === "zh-CN" ? "夜魇" : "Dire";
  return locale === "zh-CN" ? "均势" : "Even";
}
function featureNumber(features: Record<string, unknown>, key: string): number | null { const value = features[key]; return typeof value === "number" && Number.isFinite(value) ? value : null; }
function nearestCurrentEdge(curve: DraftPoint[], seconds: number | null | undefined): number | null {
  if (seconds == null || seconds < 20 * 60 || !curve.length) return null;
  const minute = Math.floor(seconds / 60);
  const point = curve.reduce((best, item) => Math.abs(item.minute - minute) < Math.abs(best.minute - minute) ? item : best);
  return point.adjusted_radiant_edge ?? point.pure_radiant_edge;
}
function peakEdge(curve: DraftPoint[]): { edge: number; minute: number } | null {
  let best: { edge: number; minute: number } | null = null;
  curve.forEach((point) => { const edge = point.adjusted_radiant_edge ?? point.pure_radiant_edge; if (edge != null && (best == null || Math.abs(edge) > Math.abs(best.edge))) best = { edge, minute: point.minute }; });
  return best;
}
function edgeAfterMinute(curve: DraftPoint[], minute: number): number | null {
  const sorted = [...curve].sort((a, b) => a.minute - b.minute);
  const point = sorted.find((item) => item.minute > minute) ?? sorted.at(-1);
  return point?.adjusted_radiant_edge ?? point?.pure_radiant_edge ?? null;
}
function edgeText(value: number, locale: string): string { const side = edgeSide(value); return side === "even" ? (locale === "zh-CN" ? "均势" : "Even") : `${sideLabel(side, locale)} +${Math.abs(value).toFixed(1)}pp`; }
