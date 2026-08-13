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
  const { t } = useI18n();
  const history = "snapshot_payload" in match ? match.snapshot_payload?.history : undefined;
  const teamAHistory = history?.team_a as TeamHistory | undefined;
  const teamBHistory = history?.team_b as TeamHistory | undefined;
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
        <div className="empty-rail-msg">{t("noHistoricalSnapshot")}</div>
      ) : (
        <div className="history-table">
          <div className="history-row header-row">
            <span className="col-label">Metric</span>
            <span className="col-val radiant">{teamA}</span>
            <span className="col-val dire">{teamB}</span>
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
