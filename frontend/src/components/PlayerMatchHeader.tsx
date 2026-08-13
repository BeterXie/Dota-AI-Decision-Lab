import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { useI18n } from "../i18n";
import { getTeamAbbreviation } from "../utils/dotaAssets";
import { formatOdds, getMatchDisplayPhase, median, primaryMarketPair } from "../utils/presentation";

interface PlayerMatchHeaderProps {
  match: MapSummary | MapDetail;
}

const teamAStyle: React.CSSProperties = { background: "rgba(124,156,255,.12)", color: "#7C9CFF", border: "1px solid rgba(124,156,255,.30)" };
const teamBStyle: React.CSSProperties = { background: "rgba(156,130,255,.12)", color: "#9C82FF", border: "1px solid rgba(156,130,255,.30)" };

export const PlayerMatchHeader: React.FC<PlayerMatchHeaderProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const teamA = match.team_a?.name || t("unknownTeam");
  const teamB = match.team_b?.name || t("unknownTeam");
  const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
  const phase = getMatchDisplayPhase(match);
  const gameTime = match.live?.game_time_seconds;
  const hasLiveScore = match.live?.radiant_kills != null && match.live?.dire_kills != null;
  const aiMedian = median(
    match.decisions
      .map((decision) => decision.decision?.fair_probability_a)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  );
  const marketA = match.market_quality?.eligible ? pair?.teamA.fair_probability ?? null : null;
  const modelMarketGap = aiMedian != null && marketA != null ? (aiMedian - marketA) * 100 : null;

  return (
    <section className="match-hero-header player-match-header">
      <div className="header-meta-row">
        <span className="meta-league">
          {match.tournament_name || t("unknownTournament")}
          {match.round ? ` · ${match.round.toUpperCase()}` : ""}
          {match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}
        </span>
        <span className={`meta-live-badge ${phase === "LIVE" ? "live" : ""}`}>
          {phase === "LIVE" && gameTime != null ? `● LIVE ${formatGameTime(gameTime)}` : phaseLabel(phase, locale)}
        </span>
        <span className="meta-quality-tag">
          {t("dataQuality")}: <strong className="quality-val">{match.latest_snapshot?.mode || t("noSnapshot")}</strong>
        </span>
      </div>

      <div className="header-scoreboard player-scoreboard">
        <div className="team-cell team-radiant">
          <div className="team-logo-avatar team-a-order" style={teamAStyle}>{getTeamAbbreviation(teamA)}</div>
          <div className="team-info">
            <span className="team-side-label">TEAM A</span>
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
                {locale === "zh-CN" ? "天辉" : "RADIANT"}{gameTime != null ? ` · ${formatGameTime(gameTime)} · ` : " · "}{locale === "zh-CN" ? "夜魇" : "DIRE"}
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
            <span className="team-side-label">TEAM B</span>
            <h2 className="team-name">{teamB}</h2>
            <div className="team-odds-pill">{formatOdds(pair?.teamB.price)}</div>
          </div>
          <div className="team-logo-avatar team-b-order" style={teamBStyle}>{getTeamAbbreviation(teamB)}</div>
        </div>
      </div>

      <div className="player-intelligence-strip">
        <div>
          <span>{locale === "zh-CN" ? "AI 中位 A 概率" : "AI median A"}</span>
          <strong>{formatProbability(aiMedian, locale)}</strong>
        </div>
        <div>
          <span>{locale === "zh-CN" ? "市场 A 概率" : "Market A"}</span>
          <strong>{formatProbability(marketA, locale)}</strong>
        </div>
        <div className={modelMarketGap == null ? "" : modelMarketGap >= 0 ? "positive-gap" : "negative-gap"}>
          <span>{locale === "zh-CN" ? "模型 - 市场" : "Model - market"}</span>
          <strong>{modelMarketGap == null ? "—" : `${modelMarketGap >= 0 ? "+" : ""}${modelMarketGap.toFixed(1)}pp`}</strong>
        </div>
        <div>
          <span>{t("radiantNetWorthLead")}</span>
          <strong>{formatNetWorth(match.live?.radiant_nw_lead, locale)}</strong>
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

function formatGameTime(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function formatProbability(value: number | null, locale: string): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function formatNetWorth(value: number | null | undefined, locale: string): string {
  if (value == null) return "—";
  if (value === 0) return locale === "zh-CN" ? "均势" : "Even";
  const side = value > 0 ? (locale === "zh-CN" ? "天辉" : "Radiant") : (locale === "zh-CN" ? "夜魇" : "Dire");
  const abs = Math.abs(value);
  const amount = abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : String(abs);
  return `${side} +${amount}`;
}
