import React from "react";
import type { LiveObservation, MapDetail, MapSummary } from "../api";
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
  const changes = React.useMemo(() => liveChanges(match), [match]);
  const gameTime = live?.game_time_seconds;
  const gameTimeText = gameTime == null
    ? "—"
    : `${Math.floor(gameTime / 60)}:${String(gameTime % 60).padStart(2, "0")}`;
  const effectiveAge = freshness.effectiveAgeSeconds;
  const messageAge = live?.message_age_seconds;
  // Keep in sync with the backend live_state_max_age_seconds (currently 120s:
  // DLTV state is event-driven every ~40-60s, so 45s falsely flags staleness).
  const liveMaxAgeSeconds = 120;
  const isStale = freshness.complete === false || (effectiveAge != null && effectiveAge > liveMaxAgeSeconds);
  const syncStatus = isStale ? "LIVE_STALE" : match.sync?.status || "UNKNOWN";
  const syncIsSafe = syncStatus === "SAFE";
  const dataLagSeconds = match.latest_snapshot?.quality?.live_anchors?.data_lag_seconds ?? null;
  const lagMinutes = dataLagSeconds != null ? Math.round(dataLagSeconds / 60) : null;
  const showBroadcastLag = lagMinutes != null && lagMinutes >= 1;

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
          {showBroadcastLag && (
            <div className="broadcast-lag-banner">
              {locale === "zh-CN"
                ? `直播画面状态 · 落后实时赔率约 ${lagMinutes} 分钟`
                : `Broadcast state · lags real-time odds by ~${lagMinutes} min`}
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

          {Object.keys(changes).length > 0 && (
            <div className="live-change-strip">
              {[60, 180, 300, 600].map((seconds) => {
                const item = changes[seconds];
                if (!item) return null;
                return (
                  <div className="live-change-item" key={seconds}>
                    <span>{seconds / 60}m</span>
                    <strong>{formatDeltaLead(item.nwDelta, locale, sides?.radiant.name, sides?.dire.name)}</strong>
                    <small>{locale === "zh-CN" ? "击杀" : "Kills"} {item.radiantKills}:{item.direKills}</small>
                  </div>
                );
              })}
            </div>
          )}

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

function liveChanges(match: MapSummary | MapDetail) {
  if (!("live_timeline" in match) || match.live_timeline.length < 2) return {};
  const points = match.live_timeline
    .filter((item) => item.game_time_seconds != null)
    .sort((a, b) => (a.game_time_seconds ?? 0) - (b.game_time_seconds ?? 0));
  const current = points.at(-1);
  if (current?.game_time_seconds == null) return {};
  const result: Record<number, { nwDelta: number; radiantKills: number; direKills: number }> = {};
  for (const seconds of [60, 180, 300, 600]) {
    const target = current.game_time_seconds - seconds;
    const baseline = nearestGameTime(points, target);
    const tolerance = Math.min(90, Math.max(20, seconds * 0.25));
    if (baseline?.game_time_seconds == null || Math.abs(baseline.game_time_seconds - target) > tolerance) continue;
    if (current.radiant_nw_lead == null || baseline.radiant_nw_lead == null) continue;
    result[seconds] = {
      nwDelta: current.radiant_nw_lead - baseline.radiant_nw_lead,
      radiantKills: Math.max(0, (current.radiant_kills ?? 0) - (baseline.radiant_kills ?? 0)),
      direKills: Math.max(0, (current.dire_kills ?? 0) - (baseline.dire_kills ?? 0))
    };
  }
  return result;
}

function nearestGameTime(points: LiveObservation[], target: number) {
  return points.reduce<LiveObservation | null>((best, item) => {
    if (item.game_time_seconds == null) return best;
    if (best?.game_time_seconds == null) return item;
    return Math.abs(item.game_time_seconds - target) < Math.abs(best.game_time_seconds - target) ? item : best;
  }, null);
}

function formatDeltaLead(value: number, locale: string, radiantTeam?: string, direTeam?: string) {
  if (value === 0) return locale === "zh-CN" ? "持平" : "Flat";
  const side = value > 0 ? "radiant" : "dire";
  return `${sideLabel(side, locale, side === "radiant" ? radiantTeam : direTeam)} +${Math.abs(value).toLocaleString(locale)}`;
}

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
