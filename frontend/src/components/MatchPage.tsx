import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchMap,
  fetchRuntime,
  queryKeys,
  type AiDecision,
  type MapDetail,
  type MapSummary
} from "../api";
import type { AuthSessionState } from "../authApi";
import { eventHref, eventName, isSeriesOngoing } from "../events";
import { shouldPollMatchFrequently } from "../matchPhase";
import { aiAccessScope, findMatchByRoute, type AiAccessScope } from "../matches";
import { useI18n } from "../i18n";
import { CanonicalMarketCard } from "./CanonicalMarketCard";
import { LineupCard } from "./LineupCard";
import { MatchLivePulse } from "./MatchLivePulse";
import { PlayerDraftAdvantageCard } from "./PlayerDraftAdvantageCard";
import { PlayerAiDecisionStrip } from "./PlayerAiDecisionStrip";
import { TeamCrest, UiIcon } from "./VisualIdentity";
import { resolveVerifiedMapSides } from "../utils/mapSides";
import { matchPhaseBadgePresentation } from "../utils/presentation";

interface MatchPageProps {
  matches: MapSummary[];
  matchesLoading: boolean;
  routeId: string;
  session: AuthSessionState | undefined;
  onLogin: () => void;
}

interface MatchAiPayload {
  canonical_map_id: string;
  canonical_series_id?: string | null;
  latest_snapshot: MapSummary["latest_snapshot"];
  decisions: AiDecision[];
  checkpoint_decisions: AiDecision[];
}

interface PublicAiSummary {
  analysis_available: boolean;
  completed_models: number;
}

export const MatchPage: React.FC<MatchPageProps> = ({
  matches,
  matchesLoading,
  routeId,
  session,
  onLogin
}) => {
  const { locale } = useI18n();
  const summary = React.useMemo(() => findMatchByRoute(matches, routeId), [matches, routeId]);
  const canonicalMapId = summary?.canonical_map_id ?? (summary?.entity_type === "SERIES" ? null : routeId);
  const detail = useQuery({
    queryKey: canonicalMapId ? queryKeys.map(canonicalMapId) : ["map", "unresolved", routeId],
    queryFn: () => fetchMap(canonicalMapId!),
    enabled: Boolean(canonicalMapId),
    retry: 1,
    refetchInterval: shouldPollMatchFrequently(summary?.phase) ? 4000 : 15_000
  });
  const match = detail.data ?? summary;
  const runtime = useQuery({
    queryKey: queryKeys.runtime,
    queryFn: fetchRuntime,
    enabled: Boolean(canonicalMapId),
    staleTime: 30_000,
    retry: 1
  });
  const scope = aiAccessScope(session, match);
  const ai = useQuery({
    queryKey: canonicalMapId ? ["map-ai", canonicalMapId] : ["map-ai", "none"],
    queryFn: () => fetchMatchAi(canonicalMapId!),
    enabled: Boolean(canonicalMapId && scope),
    retry: 1,
    refetchInterval: shouldPollMatchFrequently(match?.phase) ? 5000 : 20_000
  });

  if (matchesLoading && !match) return <MatchPageSkeleton />;
  if (!match && detail.isLoading) return <MatchPageSkeleton />;
  if (!match && detail.isError) return <MatchNotFound locale={locale} />;
  if (!match) return <MatchNotFound locale={locale} />;

  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);
  const displayDetail = detail.data;
  const teamA = match.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const teamB = match.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const event = eventName(match);
  const seriesOngoing = isSeriesOngoing(match);
  const live = displayDetail?.live ?? match.live;
  const winnerTeamId = displayDetail?.result?.winner_team_id ?? null;
  const mapSides = resolveVerifiedMapSides(displayDetail ?? match);
  const killScore = teamKillScore(match, live, mapSides);

  return (
    <div className="match-v2">
      <section className="product-container match-crumbs">
        <a href="/events">{locale === "zh-CN" ? "赛事" : "Events"}</a>
        <span>›</span>
        <a href={eventHref(event)}>{event}</a>
        <span>›</span>
        <strong>{teamA} vs {teamB}</strong>
      </section>

      <section className="product-container match-hero">
        <div className="match-hero-topline">
          <PhaseBadge phase={match.phase} locale={locale} seriesOngoing={seriesOngoing} />
          <span>{match.round || (locale === "zh-CN" ? "比赛" : "Match")}</span>
          {match.best_of ? <span>BO{match.best_of}</span> : null}
          {match.map_number ? <span>{locale === "zh-CN" ? `第 ${match.map_number} 局` : `Map ${match.map_number}`}</span> : null}
        </div>
        <div className="match-versus">
          <TeamHero team={match.team_a} name={teamA} side="a" outcome={teamOutcome(match.team_a?.id, winnerTeamId)} />
          <MatchHeroScore
            match={match}
            live={live}
            killScore={killScore}
            locale={locale}
          />
          <TeamHero team={match.team_b} name={teamB} side="b" outcome={teamOutcome(match.team_b?.id, winnerTeamId)} />
        </div>
      </section>

      {canonicalMapId ? <SeriesNavigator match={match} activeMapId={canonicalMapId} locale={locale} seriesOngoing={seriesOngoing} /> : null}

      {canonicalMapId ? (
        <section className="product-container match-live-section">
          <MatchLivePulse
            match={displayDetail ?? match}
            locale={locale}
            liveMaxAgeSeconds={runtime.data?.live_state_max_age_seconds}
          />
        </section>
      ) : null}

      {canonicalMapId ? (
        <section className="product-container match-ai-section product-section">
          <AiMatchCard
            match={match}
            scope={scope}
            signedIn={signedIn}
            authEnabled={session?.enabled !== false}
            loading={ai.isLoading}
            data={ai.data}
            locale={locale}
            onLogin={onLogin}
          />
        </section>
      ) : null}

      {!canonicalMapId ? (
        <section className="product-container match-identity-note product-section">
          <span aria-hidden="true">◎</span>
          <div>
            <h2>{locale === "zh-CN" ? "具体地图还在确认中" : "Map identity is still being confirmed"}</h2>
            <p>{locale === "zh-CN" ? "当前先展示已确认的系列赛信息。地图身份确认后，Draft、Live、市场和 AI 权限区会自动出现。" : "Confirmed series information is shown for now. Draft, live state, market context and the AI access area will appear once the map identity is resolved."}</p>
          </div>
        </section>
      ) : (
        <>
          <section className="product-container match-intelligence-grid product-section">
            <CanonicalMarketCard match={displayDetail ?? match} />
            <PlayerDraftAdvantageCard match={displayDetail ?? match} />
          </section>

          <section className="product-container match-lineup-section product-section">
            <LineupCard match={displayDetail ?? match} />
          </section>

          <section className="product-container match-state-section product-section">
            <MatchStateCard match={match} detail={displayDetail} locale={locale} />
          </section>
        </>
      )}
    </div>
  );
};

const MatchPageSkeleton = () => (
  <div className="match-v2 product-container match-page-skeleton">
    <div className="match-skeleton-block" />
    <div className="match-skeleton-grid"><div /><div /><div /></div>
  </div>
);

const MatchNotFound: React.FC<{ locale: string }> = ({ locale }) => (
  <section className="product-container match-not-found">
    <span aria-hidden="true">◇</span>
    <h1>{locale === "zh-CN" ? "没有找到这场比赛" : "Match not found"}</h1>
    <p>{locale === "zh-CN" ? "比赛可能还没有同步，或者它的身份信息已经更新。" : "The match may not be synced yet, or its identity may have changed."}</p>
    <a className="product-btn product-btn-primary" href="/events">{locale === "zh-CN" ? "返回赛事" : "Back to events"}</a>
  </section>
);

const TeamHero: React.FC<{
  team: MapSummary["team_a"];
  name: string;
  side: "a" | "b";
  outcome: "winner" | "loser" | null;
}> = ({ team, name, side, outcome }) => (
  <div className={`match-team-hero side-${side}${outcome ? ` outcome-${outcome}` : ""}`}>
    <TeamCrest team={team} fallbackName={name} size="lg" />
    <div className="match-team-copy">
      {outcome ? (
        <span className={`match-team-result is-${outcome}`}>
          {outcome === "winner" ? <UiIcon name="trophy" size={13} /> : null}
          {outcome === "winner" ? "获胜" : "失败"}
        </span>
      ) : null}
      <h1>{name}</h1>
    </div>
  </div>
);

const MatchHeroScore: React.FC<{
  match: MapSummary;
  live: MapSummary["live"];
  killScore: { teamA: number | null; teamB: number | null };
  locale: string;
}> = ({ match, live, killScore, locale }) => {
  const hasKills = killScore.teamA != null || killScore.teamB != null;
  if (!hasKills) {
    return (
      <div className="match-score-block">
        <strong>{scoreText(match)}</strong>
        <span>{match.scheduled_at ? formatDateTime(match.scheduled_at, locale) : (locale === "zh-CN" ? "时间待确认" : "Time TBD")}</span>
      </div>
    );
  }
  return (
    <div className="match-score-block match-kill-score-block">
      <div className="match-kill-score">
        <strong>{killScore.teamA ?? "—"}</strong>
        <div className="match-kill-duration">
          <span>{locale === "zh-CN" ? "时长" : "Duration"}</span>
          <b>{formatGameClock(live?.game_time_seconds ?? null)}</b>
        </div>
        <strong>{killScore.teamB ?? "—"}</strong>
      </div>
      <span>{locale === "zh-CN" ? "本局击杀" : "Map kills"}</span>
    </div>
  );
};

const SeriesNavigator: React.FC<{ match: MapSummary; activeMapId: string; locale: string; seriesOngoing: boolean }> = ({ match, activeMapId, locale, seriesOngoing }) => {
  const maps = [...(match.series_maps ?? [])].sort((left, right) => (left.map_number ?? 99) - (right.map_number ?? 99));
  if (maps.length <= 1 && !seriesOngoing) return null;
  const teamA = match.team_a?.name || (locale === "zh-CN" ? "队伍 A" : "Team A");
  const teamB = match.team_b?.name || (locale === "zh-CN" ? "队伍 B" : "Team B");
  const mapNumber = match.map_number ?? 1;
  const continuationLabel = match.phase === "POSTMATCH"
    ? (locale === "zh-CN" ? `第 ${mapNumber} 局已结束，系列赛继续进行` : `Map ${mapNumber} is complete; the series continues`)
    : (locale === "zh-CN" ? "系列赛进行中" : "Series in progress");
  return (
    <section className="product-container match-series-navigator" aria-label={locale === "zh-CN" ? "系列赛地图" : "Series maps"}>
      <div className="match-series-summary">
        <span>{locale === "zh-CN" ? `BO${match.best_of ?? maps.length} 系列赛` : `BO${match.best_of ?? maps.length} series`}</span>
        <strong>{teamA} {scoreText(match)} {teamB}</strong>
      </div>
      {maps.length > 1 ? (
        <nav>
          {maps.map((map, index) => {
            const winner = map.winner_team_id === match.team_a?.id
              ? teamA
              : map.winner_team_id === match.team_b?.id
                ? teamB
                : null;
            const currentMapNumber = map.map_number ?? index + 1;
            const active = map.canonical_map_id === activeMapId;
            return (
              <a
                key={map.canonical_map_id}
                className={active ? "is-active" : ""}
                href={`/matches/${encodeURIComponent(map.canonical_map_id)}`}
                aria-current={active ? "page" : undefined}
              >
                <span>{locale === "zh-CN" ? `第 ${currentMapNumber} 局` : `Map ${currentMapNumber}`}</span>
                <small>{winner ? (locale === "zh-CN" ? `${winner} 胜` : `${winner} won`) : (locale === "zh-CN" ? "待确认" : "Pending")}</small>
              </a>
            );
          })}
        </nav>
      ) : (
        <div className="match-series-next-state">{continuationLabel}</div>
      )}
    </section>
  );
};

const MatchStateCard: React.FC<{ match: MapSummary; detail: MapDetail | undefined; locale: string }> = ({ match, detail, locale }) => {
  const resultConfirmed = Boolean(detail?.result?.winner_team_id && !detail.result.provider_conflict);
  const resultLabel = resultConfirmed
    ? (locale === "zh-CN" ? "已确认" : "Confirmed")
    : match.phase === "POSTMATCH" || match.phase === "AWAITING_RESULT"
      ? (locale === "zh-CN" ? "等待确认" : "Awaiting confirmation")
      : "—";
  return (
    <article className="match-signal-card">
      <div className="match-card-kicker"><span aria-hidden="true">◎</span>{locale === "zh-CN" ? "数据状态" : "Data status"}</div>
      <div className="match-state-list">
        <StateLine label={locale === "zh-CN" ? "身份" : "Identity"} value={match.identity_status === "RESOLVED" ? (locale === "zh-CN" ? "已确认" : "Resolved") : (locale === "zh-CN" ? "确认中" : "Pending")} />
        <StateLine label={locale === "zh-CN" ? "Draft" : "Draft"} value={match.draft?.complete ? (locale === "zh-CN" ? "完整" : "Complete") : match.draft ? (locale === "zh-CN" ? "采集中" : "Collecting") : (locale === "zh-CN" ? "暂无" : "Not available")} />
        <StateLine label={locale === "zh-CN" ? "赛果" : "Result"} value={resultLabel} />
        <StateLine label={locale === "zh-CN" ? "最新数据" : "Latest data"} value={latestObservedAt(detail ?? match, locale)} />
      </div>
    </article>
  );
};

const StateLine: React.FC<{ label: string; value: string }> = ({ label, value }) => <div><span>{label}</span><strong>{value}</strong></div>;

const AiMatchCard: React.FC<{
  match: MapSummary;
  scope: AiAccessScope;
  signedIn: boolean;
  authEnabled: boolean;
  loading: boolean;
  data: MatchAiPayload | undefined;
  locale: string;
  onLogin: () => void;
}> = ({ match, scope, signedIn, authEnabled, loading, data, locale, onLogin }) => {
  const decisionRounds = data?.checkpoint_decisions?.length
    ? data.checkpoint_decisions
    : data?.decisions ?? [];
  const successful = decisionRounds.filter((decision) => decision.parse_status === "SUCCESS" && decision.decision);
  const publicAi = (match as MapSummary & { ai_access?: PublicAiSummary }).ai_access;
  const decisionGenerated = publicAi
    ? publicAi.analysis_available || publicAi.completed_models > 0
    : Boolean(match.latest_snapshot);
  const billingHref = match.series_id ? `/billing?series=${encodeURIComponent(match.series_id)}` : "/billing";
  const accessHeading = !authEnabled
    ? (locale === "zh-CN" ? "AI 权限当前不可用" : "AI access is unavailable")
    : !signedIn
      ? (locale === "zh-CN" ? "登录后查看完整 AI 预测" : "Sign in to view the full AI prediction")
      : (locale === "zh-CN" ? "解锁这场比赛的 AI 预测" : "Unlock this match's AI prediction");
  return (
    <article className={`match-ai-card ${scope ? "has-access" : "is-locked"}`}>
      <PanelHeading kicker="AI INTELLIGENCE" title={locale === "zh-CN" ? "AI 怎么看这场比赛" : "How AI sees this match"} aside={scope ? scopeLabel(scope, locale) : undefined} />
      {scope ? (
        loading ? <div className="match-ai-loading"><span /><span /><span /></div> : successful.length > 0 ? (
          <PlayerAiDecisionStrip decisions={successful} embedded />
        ) : <EmptyCardMessage text={locale === "zh-CN" ? "你的权限已生效，但这场比赛暂时还没有成功的 AI 预测。" : "Your access is active, but this match has no successful AI prediction yet."} />
      ) : (
        <div className={`match-ai-lock ${decisionGenerated ? "has-decision" : "is-pending"}`}>
          <div className="match-ai-preview" aria-hidden="true">
            <div className="match-ai-preview-head"><span /><i /><i /></div>
            {[
              "model-a",
              "model-b",
              "model-c"
            ].map((key) => (
              <div className="match-ai-preview-row" key={key}>
                <span />
                <div><b /><small /></div>
                <i />
              </div>
            ))}
          </div>
          <div className="match-ai-lock-content">
            <span className="match-ai-lock-icon" aria-hidden="true"><UiIcon name="lock" size={18} /></span>
            <span className={`match-ai-lock-status ${decisionGenerated ? "is-ready" : "is-pending"}`} role="status">
              {decisionGenerated
                ? (locale === "zh-CN" ? "AI 预测已生成" : "AI prediction is ready")
                : (locale === "zh-CN" ? "AI 预测尚未生成" : "AI prediction is not ready yet")}
            </span>
            <h3>{accessHeading}</h3>
            <p>{decisionGenerated
              ? (locale === "zh-CN" ? "解锁后查看完整预测、置信度和分析理由。" : "Unlock to view the full prediction, confidence, and reasoning.")
              : (locale === "zh-CN" ? "预测生成后会显示在这里，解锁后可实时查看。" : "The prediction will appear here once generated. Unlock to follow it in real time.")}</p>
            {authEnabled && (!signedIn ? <button className="product-btn product-btn-primary" type="button" onClick={onLogin}>{locale === "zh-CN" ? "登录" : "Sign in"}<span>→</span></button> : <a className="product-btn product-btn-primary" href={billingHref}>{locale === "zh-CN" ? "查看赛事 Pass" : "View competition pass"}<span>→</span></a>)}
          </div>
        </div>
      )}
      <p className="match-ai-disclaimer">{locale === "zh-CN" ? "AI 内容用于赛事分析与预测积分验证。积分不可充值、提现、转让或兑换，平台不执行真实资金投注。" : "AI content supports match analysis and prediction-points evaluation. Points cannot be purchased, withdrawn, transferred, or redeemed, and the service does not execute real-money wagers."}</p>
    </article>
  );
};

const PanelHeading: React.FC<{ kicker: string; title: string; aside?: string }> = ({ kicker, title, aside }) => (
  <div className="match-panel-heading"><div><span className="home-eyebrow">{kicker}</span><h2>{title}</h2></div>{aside ? <em>{aside}</em> : null}</div>
);

const EmptyCardMessage: React.FC<{ text: string }> = ({ text }) => <div className="match-empty-message">{text}</div>;

const PhaseBadge: React.FC<{ phase: MapSummary["phase"]; locale: string; seriesOngoing: boolean }> = ({ phase, locale, seriesOngoing }) => {
  const { key, text } = matchPhaseBadgePresentation(phase, locale, seriesOngoing);
  return <span className={`match-phase-badge is-${key}`}><i aria-hidden="true" />{text}</span>;
};

function scoreText(match: MapSummary): string {
  return match.series_score ? `${match.series_score.team_a} : ${match.series_score.team_b}` : "VS";
}

function teamOutcome(teamId: string | undefined, winnerTeamId: string | null): "winner" | "loser" | null {
  if (!winnerTeamId || !teamId) return null;
  return teamId === winnerTeamId ? "winner" : "loser";
}

function teamKillScore(
  match: MapSummary,
  live: MapSummary["live"],
  sides: ReturnType<typeof resolveVerifiedMapSides>,
): { teamA: number | null; teamB: number | null } {
  if (!live || !sides) return { teamA: null, teamB: null };
  const teamARadiant = sides?.radiant.id === match.team_a?.id;
  return {
    teamA: teamARadiant ? live.radiant_kills : live.dire_kills,
    teamB: teamARadiant ? live.dire_kills : live.radiant_kills,
  };
}

function formatDateTime(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

function formatGameClock(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const absolute = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(absolute / 60);
  const remainder = String(absolute % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function latestObservedAt(match: MapSummary, locale: string): string {
  const candidates = [
    match.live?.last_message_received_at,
    match.draft?.observed_at,
    match.provider_observed_at,
    ...match.market.map((item) => item.received_at)
  ].filter((value): value is string => Boolean(value));
  if (!candidates.length) return "—";
  candidates.sort((left, right) => Date.parse(right) - Date.parse(left));
  return formatDateTime(candidates[0], locale);
}

function scopeLabel(scope: Exclude<AiAccessScope, null>, locale: string): string {
  if (locale !== "zh-CN") {
    return scope === "GLOBAL"
      ? "Global access"
      : scope === "EVENT"
        ? "Event Pass"
        : scope === "SERIES"
        ? "Series Pass"
          : scope === "FREE"
            ? "Free group stage"
            : scope === "POSTMATCH"
              ? "Post-match public"
              : "Map access";
  }
  return scope === "GLOBAL"
    ? "全局权限"
    : scope === "EVENT"
      ? "赛事 Pass"
      : scope === "SERIES"
      ? "系列赛 Pass"
      : scope === "FREE"
        ? "Free 小组赛"
        : scope === "POSTMATCH"
          ? "赛后公开"
          : "本局权限";
}

async function fetchMatchAi(id: string): Promise<MatchAiPayload> {
  const response = await fetch(`/api/maps/${id}/ai-decisions`, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<MatchAiPayload>;
}
