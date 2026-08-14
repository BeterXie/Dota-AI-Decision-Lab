import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { useI18n } from "../i18n";
import { getTeamAbbreviation, getTeamLogoUrl } from "../utils/dotaAssets";
import { resolveVerifiedMapSides } from "../utils/mapSides";
import { formatOdds, getMatchDisplayPhase, median, primaryMarketPair } from "../utils/presentation";

interface PlayerMatchHeaderProps {
  match: MapSummary | MapDetail;
  onSelectMap?: (id: string) => void;
}

const teamAStyle: React.CSSProperties = { background: "rgba(124,156,255,.12)", color: "#7C9CFF", border: "1px solid rgba(124,156,255,.30)" };
const teamBStyle: React.CSSProperties = { background: "rgba(156,130,255,.12)", color: "#9C82FF", border: "1px solid rgba(156,130,255,.30)" };

export const PlayerMatchHeader: React.FC<PlayerMatchHeaderProps> = ({ match, onSelectMap }) => {
  const { locale, t } = useI18n();
  const teamA = match.team_a?.name || t("unknownTeam");
  const teamB = match.team_b?.name || t("unknownTeam");
  const teamALogo = getTeamLogoUrl(teamA);
  const teamBLogo = getTeamLogoUrl(teamB);
  const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
  const phase = getMatchDisplayPhase(match);
  const gameTime = match.live?.game_time_seconds;
  const hasLiveScore = match.live?.radiant_kills != null && match.live?.dire_kills != null;
  const sides = resolveVerifiedMapSides(match);
  const teamASide = sides?.radiant.seriesSide === "A" ? "radiant" : sides?.dire.seriesSide === "A" ? "dire" : null;
  const teamBSide = sides?.radiant.seriesSide === "B" ? "radiant" : sides?.dire.seriesSide === "B" ? "dire" : null;
  const aiMedian = median(
    match.decisions
      .map((decision) => decision.decision?.fair_probability_a)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  );
  // Derived no-vig probability wins; the raw observation's fair_probability is
  // a fallback for payloads that predate current_market_view.
  const marketA = match.market_quality?.eligible
    ? match.current_market_view?.team_a?.fair_probability ?? pair?.teamA.fair_probability ?? null
    : null;
  const modelMarketGap = aiMedian != null && marketA != null ? (aiMedian - marketA) * 100 : null;

  const seriesMaps = match.series_maps || [];
  const bestOf = match.best_of || (match.round?.toUpperCase().startsWith("BO") ? parseInt(match.round.slice(2), 10) : null);
  const scoreA = match.series_score?.team_a ?? 0;
  const scoreB = match.series_score?.team_b ?? 0;

  return (
    <section className="match-hero-header player-match-header">
      <div className="header-meta-row">
        <span className="meta-league">
          {match.tournament_name || t("unknownTournament")}
          {bestOf ? ` · BO${bestOf}` : match.round ? ` · ${match.round.toUpperCase()}` : ""}
          {match.series_score ? ` · (系列赛 ${scoreA} - ${scoreB})` : ""}
          {match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}
        </span>
        <span className={`meta-live-badge ${phase === "LIVE" ? "live" : ""}`}>
          {phase === "LIVE" && gameTime != null ? `● LIVE ${formatGameTime(gameTime)}` : phaseLabel(phase, locale)}
        </span>
        <span className="meta-quality-tag">
          {t("dataQuality")}: <strong className="quality-val">{match.latest_snapshot?.mode || t("noSnapshot")}</strong>
        </span>
      </div>

      {seriesMaps.length > 1 && (
        <div className="map-selector-bar" role="tablist" aria-label="地图选择">
          <span className="map-selector-title">{locale === "zh-CN" ? "单局切换" : "Maps"}:</span>
          {seriesMaps.map((sm, index) => {
            const mapNum = sm.map_number || index + 1;
            const isCurrent = sm.canonical_map_id === match.canonical_map_id || sm.canonical_map_id === match.id;
            let statusText = "";
            if (sm.winner_team_id) {
              const winnerName = sm.winner_team_id === match.team_a?.id ? teamA : sm.winner_team_id === match.team_b?.id ? teamB : "胜";
              statusText = `${winnerName} 胜`;
            } else if (isCurrent && phase === "LIVE") {
              statusText = "● 进行中";
            }
            return (
              <button
                type="button"
                key={sm.canonical_map_id}
                role="tab"
                aria-selected={isCurrent}
                className={`map-selector-pill ${isCurrent ? "active" : ""}`}
                onClick={() => onSelectMap && onSelectMap(sm.canonical_map_id)}
              >
                <b>{t("map")} {mapNum}</b>
                {statusText ? <small>{statusText}</small> : null}
              </button>
            );
          })}
        </div>
      )}

      <div className="header-scoreboard player-scoreboard">
        <div className="team-cell team-radiant">
          <div className="team-logo-avatar team-a-order" style={teamAStyle}>
            {teamALogo ? (
              <img
                src={teamALogo}
                alt={teamA}
                className="team-logo-img"
                onError={(e) => { (e.currentTarget as HTMLElement).style.display = "none"; }}
              />
            ) : null}
            <span className="team-logo-fallback">{getTeamAbbreviation(teamA)}</span>
          </div>
          <div className="team-info">
            <span className="team-side-label">TEAM A{teamASide ? ` · ${mapSideName(teamASide, locale)}` : ""}</span>
            <h2 className="team-name">{teamA}</h2>
            <div className="team-odds-pill">{formatOdds(pair?.teamA.price)}</div>
          </div>
        </div>

        <div className="score-cell">
          {hasLiveScore ? (
            <>
              <div className="score-number" aria-label={locale === "zh-CN" ? "天辉与夜魇击杀比分" : "Radiant versus Dire kill score"}>
                <span className="score-radiant">{match.live?.radiant_kills}</span>
                <span className="score-divider">:</span>
                <span className="score-dire">{match.live?.dire_kills}</span>
              </div>
              <span className="score-time">
                {sideScoreLabel(sides?.radiant.name, "radiant", locale)}
                {gameTime != null ? ` · ${formatGameTime(gameTime)} · ` : " · "}
                {sideScoreLabel(sides?.dire.name, "dire", locale)}
              </span>
            </>
          ) : (
            <>
              <div className="score-number"><span className="score-divider">VS</span></div>
              <span className="score-time">{phaseLabel(phase, locale)}</span>
            </>
          )}
        </div>

        <div className="team-cell team-dire">
          <div className="team-info align-right">
            <span className="team-side-label">TEAM B{teamBSide ? ` · ${mapSideName(teamBSide, locale)}` : ""}</span>
            <h2 className="team-name">{teamB}</h2>
            <div className="team-odds-pill">{formatOdds(pair?.teamB.price)}</div>
          </div>
          <div className="team-logo-avatar team-b-order" style={teamBStyle}>
            {teamBLogo ? (
              <img
                src={teamBLogo}
                alt={teamB}
                className="team-logo-img"
                onError={(e) => { (e.currentTarget as HTMLElement).style.display = "none"; }}
              />
            ) : null}
            <span className="team-logo-fallback">{getTeamAbbreviation(teamB)}</span>
          </div>
        </div>
      </div>

      <div className="player-intelligence-strip">
        <div>
          <span>{locale === "zh-CN" ? "AI 中位 A（决策时）" : "AI median A · decision"}</span>
          <strong>{formatProbability(aiMedian, locale)}</strong>
        </div>
        <div>
          <span>{locale === "zh-CN" ? "当前市场 A" : "Market A · now"}</span>
          <strong>{formatProbability(marketA, locale)}</strong>
        </div>
        <div className={modelMarketGap == null ? "" : modelMarketGap >= 0 ? "positive-gap" : "negative-gap"}>
          <span>{locale === "zh-CN" ? "决策模型 - 当前市场" : "Decision model - market now"}</span>
          <strong>{modelMarketGap == null ? "—" : `${modelMarketGap >= 0 ? "+" : ""}${modelMarketGap.toFixed(1)}pp`}</strong>
        </div>
        <div>
          <span>{t("radiantNetWorthLead")}</span>
          <strong>{formatNetWorth(match.live?.radiant_nw_lead, locale, sides?.radiant.name, sides?.dire.name)}</strong>
        </div>
      </div>
    </section>
  );
};

function phaseLabel(phase: ReturnType<typeof getMatchDisplayPhase>, locale: string): string {
  const zh = locale === "zh-CN";
  if (phase === "UPCOMING") return zh ? "即将开始" : "UPCOMING";
  if (phase === "AWAITING_RESULT") return zh ? "等待赛果" : "AWAITING RESULT";
  if (phase === "POSTMATCH") return zh ? "已结束" : "POSTMATCH";
  if (phase === "LIVE") return "LIVE";
  return zh ? "追踪中" : "TRACKED";
}

function mapSideName(side: "radiant" | "dire", locale: string): string {
  return side === "radiant"
    ? (locale === "zh-CN" ? "天辉" : "RADIANT")
    : (locale === "zh-CN" ? "夜魇" : "DIRE");
}

function sideScoreLabel(teamName: string | undefined, side: "radiant" | "dire", locale: string): string {
  const sideName = mapSideName(side, locale);
  return teamName ? `${teamName} · ${sideName}` : sideName;
}

function formatGameTime(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function formatProbability(value: number | null, locale: string): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function formatNetWorth(
  value: number | null | undefined,
  locale: string,
  radiantTeam?: string,
  direTeam?: string
): string {
  if (value == null) return "—";
  if (value === 0) return locale === "zh-CN" ? "均势" : "Even";
  const side = value > 0 ? "radiant" : "dire";
  const teamName = side === "radiant" ? radiantTeam : direTeam;
  const abs = Math.abs(value);
  const amount = abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : String(abs);
  return `${sideScoreLabel(teamName, side, locale)} +${amount}`;
}
