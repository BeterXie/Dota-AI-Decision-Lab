import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { translateStatus, useI18n } from "../i18n";

interface DecisionTrustBannerProps {
  match: MapSummary | MapDetail;
}

export const DecisionTrustBanner: React.FC<DecisionTrustBannerProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const quality = match.latest_snapshot?.quality;
  const blockers = quality?.blockers || [];
  const warnings = quality?.warnings || [];
  const mode = match.latest_snapshot?.mode;
  const statusType = blockers.length ? "blocked" : warnings.length || !mode ? "degraded" : "healthy";
  const title = blockers.length
    ? t("cannotDecide")
    : warnings.length || !mode
      ? t("limitedDecision")
      : t("decisionReady");
  const details = [...blockers, ...warnings].join(" · ") || t("qualityChecksPassed");

  return (
    <div className={`trust-banner trust-${statusType}`}>
      <div className="trust-content">
        <span className="trust-title">{title}</span>
        <span className="trust-details">{details}</span>
      </div>
      <div className="trust-pill-group">
        <span className={`trust-pill ${statusType}`}>
          {mode ? translateStatus(mode, locale) : t("noSnapshot")}
        </span>
        <span className="trust-pill">{translateStatus(match.phase, locale)}</span>
      </div>
    </div>
  );
};
