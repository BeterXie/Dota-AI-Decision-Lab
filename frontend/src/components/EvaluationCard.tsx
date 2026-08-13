import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { useI18n } from "../i18n";

interface EvaluationCardProps {
  match: MapSummary | MapDetail;
}

export const EvaluationCard: React.FC<EvaluationCardProps> = ({ match }) => {
  const { t } = useI18n();
  const detail = "result" in match ? match : null;
  const winnerId = detail?.result?.winner_team_id;
  const winner = winnerId === match.team_a?.id
    ? match.team_a?.name
    : winnerId === match.team_b?.id
      ? match.team_b?.name
      : null;
  const evidenceCount = detail?.result_evidence?.length || 0;

  return (
    <div className="analytics-card evaluation-card">
      <div className="card-header"><span className="card-title">{t("evaluation")}</span></div>
      <div className="eval-avg-row">
        <div className="avg-box">
          <span className="avg-val">{evidenceCount}</span>
          <span className="avg-lbl">{t("resultEvidence")}</span>
        </div>
        <div className="result-box">
          <span className="res-val">{winner || "—"}</span>
          <span className="res-lbl">{t("winner")}</span>
        </div>
      </div>
      <div className="eval-footer-note">
        {detail?.result?.provider_conflict ? t("resultConflict") : t("noEvaluationEvidence")}
      </div>
    </div>
  );
};
