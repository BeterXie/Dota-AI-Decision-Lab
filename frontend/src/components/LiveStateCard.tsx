import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { translateStatus, useI18n } from "../i18n";
import { resolveDecisionLiveFreshness } from "../utils/liveFreshness";
import { resolveVerifiedMapSides } from "../utils/mapSides";

interface LiveStateCardProps {
  match: MapSummary | MapDetail;
}

export const LiveStateCard: React.FC<LiveStateCardProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const live = match.live;
  const sides = resolveVerifiedMapSides(match);
  const freshness = resolveDecisionLiveFreshness(match);
  const gameTime = live?.game_time_seconds;
  const gameTimeText = gameTime == null
    ? "—"
    : `${Math.floor(gameTime / 60)}:${String(gameTime % 60).padStart(2, "0")}`;
  const effectiveAge = freshness.effectiveAgeSeconds;
  const messageAge = live?.message_age_seconds;
  const isStale = freshness.complete === false || (effectiveAge != null && effectiveAge > 45);
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
              {translateStatus("LIVE_STALE", locale)}
              {effectiveAge != null ? ` · ${Math.round(effectiveAge)}s` : ""}
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
                <span className="radiant-txt">{sideLabel("radiant", locale, sides?.radiant.name)} {live.radiant_kills ?? "—"}</span>
                {" · "}
                <span className="dire-txt">{live.dire_kills ?? "—"} {sideLabel("dire", locale, sides?.dire.name)}</span>
              </span>
            </div>
            <div className="live-stat-row">
              <span className="stat-label">{t("radiantNetWorthLead")}</span>
              <span className="stat-value">{formatNetWorth(live.radiant_nw_lead, locale, sides?.radiant.name, sides?.dire.name)}</span>
            </div>
            <div className="live-stat-row">
              <span className="stat-label">{t("firstBlood")}</span>
              <span className="stat-value">{formatMapSide(live.first_blood, locale, sides?.radiant.name, sides?.dire.name)}</span>
            </div>
          </div>
          <div className="live-sync-footer">
            <span>
              {t("effectiveStateAge")}: {freshness.complete === false
                ? (locale === "zh-CN" ? "字段不完整" : "INCOMPLETE")
                : effectiveAge == null
                  ? "—"
                  : `${Math.round(effectiveAge)}s`}
            </span>
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

function sideLabel(side: "radiant" | "dire", locale: string, teamName?: string): string {
  const sideName = side === "radiant"
    ? (locale === "zh-CN" ? "天辉" : "Radiant")
    : (locale === "zh-CN" ? "夜魇" : "Dire");
  return teamName ? `${teamName} · ${sideName}` : sideName;
}

function formatNetWorth(
  value: number | null | undefined,
  locale: string,
  radiantTeam?: string,
  direTeam?: string
): string {
  if (value == null) return "—";
  if (value === 0) return locale === "zh-CN" ? "均势" : "Even";
  const radiantLeads = value > 0;
  return `${sideLabel(radiantLeads ? "radiant" : "dire", locale, radiantLeads ? radiantTeam : direTeam)} +${Math.abs(value).toLocaleString(locale)}`;
}

function formatMapSide(
  value: string | null | undefined,
  locale: string,
  radiantTeam?: string,
  direTeam?: string
): string {
  if (!value) return "—";
  const normalized = value.toLowerCase();
  if (normalized.includes("radiant")) return sideLabel("radiant", locale, radiantTeam);
  if (normalized.includes("dire")) return sideLabel("dire", locale, direTeam);
  return value;
}
