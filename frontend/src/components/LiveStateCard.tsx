import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { translateStatus, useI18n } from "../i18n";

interface LiveStateCardProps {
  match: MapSummary | MapDetail;
}

export const LiveStateCard: React.FC<LiveStateCardProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const live = match.live;
  const gameTime = live?.game_time_seconds;
  const gameTimeText = gameTime == null
    ? "—"
    : `${Math.floor(gameTime / 60)}:${String(gameTime % 60).padStart(2, "0")}`;
  const effectiveAge = live?.effective_state_age_seconds;
  const messageAge = live?.message_age_seconds;
  const isStale = effectiveAge != null && effectiveAge > 45;
  const syncStatus = isStale ? "LIVE_STALE" : match.sync?.status || "UNKNOWN";
  const syncIsSafe = syncStatus === "SAFE";

  return (
    <div className="analytics-card live-state-card">
      <div className="card-header">
        <span className="card-title">{t("liveState")}</span>
      </div>
      {live == null ? (
        <div className="empty-rail-msg">{t("noLiveState")}</div>
      ) : (
        <>
          {isStale && (
            <div className="stale-warning-banner">
              {translateStatus("LIVE_STALE", locale)} · {Math.round(effectiveAge)}s
            </div>
          )}
          <div className="live-state-grid">
            <div className="live-stat-row">
              <span className="stat-label">{t("gameTime")}</span>
              <span className="stat-value highlight-gold">{gameTimeText}</span>
            </div>
            <div className="live-stat-row">
              <span className="stat-label">{t("kills")}</span>
              <span className="stat-value">
                <span className="radiant-txt">{live.radiant_kills ?? "—"}</span>
                {" - "}
                <span className="dire-txt">{live.dire_kills ?? "—"}</span>
              </span>
            </div>
            <div className="live-stat-row">
              <span className="stat-label">{t("radiantNetWorthLead")}</span>
              <span className="stat-value">
                {live.radiant_nw_lead == null
                  ? "—"
                  : live.radiant_nw_lead === 0
                    ? (locale === "zh-CN" ? "均势" : "Even")
                    : `${live.radiant_nw_lead > 0 ? (locale === "zh-CN" ? "天辉" : "Radiant") : (locale === "zh-CN" ? "夜魇" : "Dire")} +${Math.abs(live.radiant_nw_lead).toLocaleString(locale)}`}
              </span>
            </div>
            <div className="live-stat-row">
              <span className="stat-label">{t("firstBlood")}</span>
              <span className="stat-value">{live.first_blood || "—"}</span>
            </div>
          </div>
          <div className="live-sync-footer">
            <span>{t("effectiveStateAge")}: {effectiveAge == null ? "—" : `${Math.round(effectiveAge)}s`}</span>
            <span className={`sync-status-tag ${syncIsSafe ? "safe" : ""}`}>
              {translateStatus(syncStatus, locale)}
            </span>
            <span>{t("messageAge")}: {messageAge == null ? "—" : `${Math.round(messageAge)}s`}</span>
          </div>
        </>
      )}
    </div>
  );
};
