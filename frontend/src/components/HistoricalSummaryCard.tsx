import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { useI18n } from "../i18n";

interface HistoricalSummaryCardProps {
  match: MapSummary | MapDetail;
}

type TeamHistory = {
  base_rating?: number | null;
  recent_form?: number | null;
  last_10?: string | null;
  roster_stability?: number | null;
};

export const HistoricalSummaryCard: React.FC<HistoricalSummaryCardProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const history = "snapshot_payload" in match ? match.snapshot_payload?.history : undefined;
  const teamAHistory = history?.team_a as TeamHistory | undefined;
  const teamBHistory = history?.team_b as TeamHistory | undefined;
  const prewarm = match.historical_prewarm;
  const teamA = match.team_a?.name || t("unknownTeam");
  const teamB = match.team_b?.name || t("unknownTeam");
  const value = (input: number | string | null | undefined, percent = false) => {
    if (input == null) return "—";
    if (typeof input === "number") return percent ? `${Math.round(input * 100)}%` : input.toFixed(1);
    return input;
  };

  return (
    <div className="analytics-card historical-card">
      <div className="card-header"><span className="card-title">{t("historical")}</span></div>
      {!teamAHistory && !teamBHistory ? (
        prewarm ? <HistoricalPrewarm prewarm={prewarm} locale={locale} /> : <div className="empty-rail-msg">{t("noHistoricalSnapshot")}</div>
      ) : (
        <div className="history-table">
          <div className="history-row header-row">
            <span className="col-label">Metric</span>
            <span className="col-val" style={{ color: "#7C9CFF" }}>{teamA}</span>
            <span className="col-val" style={{ color: "#9C82FF" }}>{teamB}</span>
          </div>
          <div className="history-row">
            <span className="col-label">{t("baseElo")}</span>
            <span className="col-val">{value(teamAHistory?.base_rating)}</span>
            <span className="col-val">{value(teamBHistory?.base_rating)}</span>
          </div>
          <div className="history-row">
            <span className="col-label">{t("recentForm")}</span>
            <span className="col-val">{value(teamAHistory?.recent_form)}</span>
            <span className="col-val">{value(teamBHistory?.recent_form)}</span>
          </div>
          <div className="history-row">
            <span className="col-label">Last 10</span>
            <span className="col-val">{value(teamAHistory?.last_10)}</span>
            <span className="col-val">{value(teamBHistory?.last_10)}</span>
          </div>
          <div className="history-row">
            <span className="col-label">{t("rosterStability")}</span>
            <span className="col-val">{value(teamAHistory?.roster_stability, true)}</span>
            <span className="col-val">{value(teamBHistory?.roster_stability, true)}</span>
          </div>
        </div>
      )}
    </div>
  );
};

function HistoricalPrewarm({ prewarm, locale }: { prewarm: NonNullable<MapSummary["historical_prewarm"]>; locale: string }) {
  const zh = locale === "zh-CN";
  return (
    <div className="history-table">
      <div className="history-row"><span className="col-label">{zh ? "队伍强度" : "Team strength"}</span><span className="col-val">{prewarm.team_strength_ready_count}/2</span><span className="col-val">{zh ? "已预热" : "ready"}</span></div>
      <div className="history-row"><span className="col-label">{zh ? "选手状态" : "Player form"}</span><span className="col-val">{prewarm.player_form_ready_count}/10</span><span className="col-val">{zh ? "已预热" : "ready"}</span></div>
      <div className="history-row"><span className="col-label">Player × Hero</span><span className="col-val">{prewarm.player_hero_ready_count}/10</span><span className="col-val">{zh ? "已预热" : "ready"}</span></div>
      <div className="history-row"><span className="col-label">{zh ? "知识截止" : "Knowledge cutoff"}</span><span className="col-val" style={{ gridColumn: "span 2" }}>{formatCutoff(prewarm.latest_knowledge_cutoff, locale)}</span></div>
    </div>
  );
}

function formatCutoff(value: string | null, locale: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "—";
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}
