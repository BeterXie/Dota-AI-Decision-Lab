import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { getTeamAbbreviation } from "../utils/dotaAssets";
import { translateStatus, useI18n } from "../i18n";

interface MatchHeaderProps {
  match: MapSummary | MapDetail;
}

export const MatchHeader: React.FC<MatchHeaderProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const teamA = match.team_a?.name || t("unknownTeam");
  const teamB = match.team_b?.name || t("unknownTeam");
  const teamAAbbr = getTeamAbbreviation(teamA);
  const teamBAbbr = getTeamAbbreviation(teamB);

  const oddsA = match.market?.[0]?.price ? Number(match.market[0].price).toFixed(2) : "—";
  const oddsB = match.market?.[1]?.price ? Number(match.market[1].price).toFixed(2) : "—";

  const isLive = match.phase === "LIVE";
  const killsA = match.live?.radiant_kills;
  const killsB = match.live?.dire_kills;
  const nwLead = match.live?.radiant_nw_lead;
  const gameTimeSeconds = match.live?.game_time_seconds;
  const gameTimeStr = gameTimeSeconds == null
    ? null
    : `${Math.floor(gameTimeSeconds / 60)}:${String(gameTimeSeconds % 60).padStart(2, "0")}`;

  const mode = match.latest_snapshot?.mode;

  return (
    <div className="match-hero-header">
      <div className="header-meta-row">
        <span className="meta-league">
          {match.tournament_name || t("unknownTournament")}
          {match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}
        </span>
        <span className={`meta-live-badge ${isLive ? "live" : ""}`}>
          {isLive && gameTimeStr
            ? `● ${translateStatus("LIVE", locale)} ${gameTimeStr}`
            : translateStatus(match.phase, locale)}
        </span>
        <span className="meta-quality-tag">
          {t("dataQuality")}: <strong className="quality-val">{mode || t("noSnapshot")}</strong>
        </span>
      </div>

      <div className="header-scoreboard">
        <div className="team-cell team-radiant">
          <div className="team-logo-avatar radiant">{teamAAbbr}</div>
          <div className="team-info">
            <h2 className="team-name">{teamA}</h2>
            <div className="team-odds-pill">{oddsA}</div>
          </div>
        </div>

        <div className="score-cell">
          <div className="score-number">
            <span className="score-radiant">{killsA ?? "—"}</span>
            <span className="score-divider">:</span>
            <span className="score-dire">{killsB ?? "—"}</span>
          </div>
        </div>

        <div className="team-cell team-dire">
          <div className="team-info align-right">
            <h2 className="team-name">{teamB}</h2>
            <div className="team-odds-pill">{oddsB}</div>
          </div>
          <div className="team-logo-avatar dire">{teamBAbbr}</div>
        </div>
      </div>

      <div className="header-lead-bar-container">
        <div className="lead-indicator">
          <span className="lead-label">{t("radiantNetWorthLead")}</span>
          <span className="lead-value">
            {nwLead == null ? "—" : `${nwLead >= 0 ? "+" : ""}${(nwLead / 1000).toFixed(1)}k`}
          </span>
        </div>
        <div className="lead-progress-track">
          <div
            className="lead-progress-fill"
            style={{ width: `${nwLead == null ? 50 : Math.min(100, Math.max(10, 50 + nwLead / 200))}%` }}
          />
        </div>
        <div className="lead-meta">
          <span>{mode || t("noSnapshot")}</span>
          <span>·</span>
          <span>
            {match.live?.message_age_seconds == null
              ? t("notObserved")
              : `${t("messageAge")} ${Math.round(match.live.message_age_seconds)}s`}
          </span>
        </div>
      </div>
    </div>
  );
};
