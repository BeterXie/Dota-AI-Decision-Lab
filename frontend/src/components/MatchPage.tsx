import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchMap,
  queryKeys,
  type AiDecision,
  type CurrentMarketLeg,
  type MapDetail,
  type MapSummary
} from "../api";
import type { AuthSessionState } from "../authApi";
import { eventHref, eventName } from "../events";
import { aiAccessScope, findMatchByRoute, type AiAccessScope } from "../matches";
import { useI18n } from "../i18n";
import { TeamCrest } from "./VisualIdentity";

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
    refetchInterval: summary?.phase === "LIVE" ? 4000 : 15_000
  });
  const match = detail.data ?? summary;
  const scope = aiAccessScope(session, match);
  const ai = useQuery({
    queryKey: canonicalMapId ? ["map-ai", canonicalMapId] : ["map-ai", "none"],
    queryFn: () => fetchMatchAi(canonicalMapId!),
    enabled: Boolean(canonicalMapId && scope),
    retry: 1,
    refetchInterval: match?.phase === "LIVE" ? 5000 : 20_000
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
  const resultWinner = winnerName(displayDetail, match);

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
          <PhaseBadge phase={match.phase} locale={locale} />
          <span>{match.round || (locale === "zh-CN" ? "比赛" : "Match")}</span>
          {match.best_of ? <span>BO{match.best_of}</span> : null}
          {match.map_number ? <span>{locale === "zh-CN" ? `第 ${match.map_number} 局` : `Map ${match.map_number}`}</span> : null}
        </div>
        <div className="match-versus">
          <TeamHero team={match.team_a} name={teamA} side="a" />
          <div className="match-score-block">
            <strong>{scoreText(match)}</strong>
            <span>{match.scheduled_at ? formatDateTime(match.scheduled_at, locale) : (locale === "zh-CN" ? "时间待确认" : "Time TBD")}</span>
            {resultWinner ? <em>{locale === "zh-CN" ? `${resultWinner} 获胜` : `${resultWinner} won`}</em> : null}
          </div>
          <TeamHero team={match.team_b} name={teamB} side="b" />
        </div>
      </section>

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
          <section className="product-container match-public-grid product-section">
            <LiveCard match={match} detail={displayDetail} locale={locale} />
            <MarketCard match={match} detail={displayDetail} locale={locale} />
            <MatchStateCard match={match} detail={displayDetail} locale={locale} />
          </section>

          <section className="product-container match-detail-grid product-section">
            <DraftCard match={match} detail={displayDetail} locale={locale} />
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
}> = ({ team, name, side }) => (
  <div className={`match-team-hero side-${side}`}>
    <TeamCrest team={team} fallbackName={name} size="lg" />
    <h1>{name}</h1>
  </div>
);

const LiveCard: React.FC<{ match: MapSummary; detail: MapDetail | undefined; locale: string }> = ({ match, detail, locale }) => {
  const live = detail?.live ?? match.live;
  return (
    <article className={`match-signal-card ${match.phase === "LIVE" ? "is-live" : ""}`}>
      <div className="match-card-kicker"><span aria-hidden="true">●</span>{locale === "zh-CN" ? "比赛进程" : "Match state"}</div>
      {live ? (
        <>
          <div className="match-live-clock">{formatGameClock(live.game_time_seconds)}</div>
          <div className="match-live-score"><strong>{live.radiant_kills ?? "—"}</strong><span>{locale === "zh-CN" ? "击杀" : "kills"}</span><strong>{live.dire_kills ?? "—"}</strong></div>
          <p>{netWorthText(live.radiant_nw_lead, match, locale)}</p>
        </>
      ) : (
        <EmptyCardMessage text={phaseEmptyText(match.phase, locale)} />
      )}
    </article>
  );
};

const MarketCard: React.FC<{ match: MapSummary; detail: MapDetail | undefined; locale: string }> = ({ match, detail, locale }) => {
  const market = detail?.current_market_view ?? match.current_market_view;
  const fallback = market ? null : latestMarketPair(detail ?? match);
  return (
    <article className="match-signal-card">
      <div className="match-card-kicker"><span aria-hidden="true">◇</span>{locale === "zh-CN" ? "市场快照" : "Market snapshot"}</div>
      {market ? (
        <div className="match-market-pair">
          <MarketLeg leg={market.team_a} name={match.team_a?.name || "A"} locale={locale} />
          <div className="match-market-overround"><strong>{market.overround == null ? "—" : `${(market.overround * 100).toFixed(1)}%`}</strong><span>{locale === "zh-CN" ? "市场水位差" : "overround"}</span></div>
          <MarketLeg leg={market.team_b} name={match.team_b?.name || "B"} locale={locale} />
        </div>
      ) : fallback ? (
        <div className="match-market-fallback">
          <span><b>{match.team_a?.name || "A"}</b><strong>{fallback.a ?? "—"}</strong></span>
          <em>vs</em>
          <span><b>{match.team_b?.name || "B"}</b><strong>{fallback.b ?? "—"}</strong></span>
        </div>
      ) : (
        <EmptyCardMessage text={locale === "zh-CN" ? "暂时没有可用的市场快照" : "No market snapshot available yet"} />
      )}
      <p className="match-card-note">{locale === "zh-CN" ? "这里只展示观测到的市场信息，不代表真实成交或收益。" : "Observed market context only; this does not represent real execution or returns."}</p>
    </article>
  );
};

const MarketLeg: React.FC<{ leg: CurrentMarketLeg; name: string; locale: string }> = ({ leg, name, locale }) => (
  <div className="match-market-leg">
    <span>{name}</span>
    <strong>{formatOdds(leg.price)}</strong>
    <small>{leg.fair_probability == null ? "—" : `${(leg.fair_probability * 100).toFixed(1)}%`} {locale === "zh-CN" ? "去水概率" : "fair"}</small>
  </div>
);

const MatchStateCard: React.FC<{ match: MapSummary; detail: MapDetail | undefined; locale: string }> = ({ match, detail, locale }) => (
  <article className="match-signal-card">
    <div className="match-card-kicker"><span aria-hidden="true">◎</span>{locale === "zh-CN" ? "数据状态" : "Data status"}</div>
    <div className="match-state-list">
      <StateLine label={locale === "zh-CN" ? "身份" : "Identity"} value={match.identity_status === "RESOLVED" ? (locale === "zh-CN" ? "已确认" : "Resolved") : (locale === "zh-CN" ? "确认中" : "Pending")} />
      <StateLine label={locale === "zh-CN" ? "Draft" : "Draft"} value={match.draft?.complete ? (locale === "zh-CN" ? "完整" : "Complete") : match.draft ? (locale === "zh-CN" ? "采集中" : "Collecting") : (locale === "zh-CN" ? "暂无" : "Not available")} />
      <StateLine label={locale === "zh-CN" ? "赛果" : "Result"} value={detail?.result ? (locale === "zh-CN" ? "已确认" : "Confirmed") : match.phase === "POSTMATCH" ? (locale === "zh-CN" ? "等待确认" : "Awaiting confirmation") : "—"} />
      <StateLine label={locale === "zh-CN" ? "最新数据" : "Latest data"} value={latestObservedAt(detail ?? match, locale)} />
    </div>
  </article>
);

const StateLine: React.FC<{ label: string; value: string }> = ({ label, value }) => <div><span>{label}</span><strong>{value}</strong></div>;

const DraftCard: React.FC<{ match: MapSummary; detail: MapDetail | undefined; locale: string }> = ({ match, detail, locale }) => {
  const draft = detail?.draft ?? match.draft;
  if (!draft) {
    return <article className="match-draft-card"><PanelHeading kicker="DRAFT" title={locale === "zh-CN" ? "阵容与选手" : "Draft & players"} /><EmptyCardMessage text={locale === "zh-CN" ? "Draft 数据还没有到达" : "Draft data has not arrived yet"} /></article>;
  }
  const radiant = draft.slots.filter((slot) => slot.side === "radiant").sort((a, b) => a.position - b.position);
  const dire = draft.slots.filter((slot) => slot.side === "dire").sort((a, b) => a.position - b.position);
  return (
    <article className="match-draft-card">
      <PanelHeading kicker="DRAFT" title={locale === "zh-CN" ? "阵容与选手" : "Draft & players"} aside={draft.complete ? (locale === "zh-CN" ? "阵容已确认" : "Draft complete") : (locale === "zh-CN" ? "阵容采集中" : "Draft collecting")} />
      <div className="match-draft-sides">
        <DraftSide title={match.team_a?.name || (locale === "zh-CN" ? "队伍 A" : "Team A")} slots={radiant} locale={locale} />
        <DraftSide title={match.team_b?.name || (locale === "zh-CN" ? "队伍 B" : "Team B")} slots={dire} locale={locale} />
      </div>
    </article>
  );
};

const DraftSide: React.FC<{ title: string; slots: NonNullable<MapSummary["draft"]>["slots"]; locale: string }> = ({ title, slots, locale }) => (
  <div className="match-draft-side">
    <h3>{title}</h3>
    <div className="match-draft-slots">
      {slots.length > 0 ? slots.map((slot) => (
        <div key={`${slot.side}-${slot.position}`}>
          <i aria-hidden="true">{slot.hero_name ? teamInitial(slot.hero_name) : slot.position}</i>
          <span><strong>{slot.hero_name || (locale === "zh-CN" ? "英雄待定" : "Hero TBD")}</strong><small>{slot.player_name || (locale === "zh-CN" ? `位置 ${slot.position}` : `Position ${slot.position}`)}</small></span>
        </div>
      )) : <EmptyCardMessage text={locale === "zh-CN" ? "阵容位置还没有确认" : "Draft slots are not confirmed yet"} />}
    </div>
  </div>
);

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
  const successful = (data?.decisions ?? []).filter((decision) => decision.parse_status === "SUCCESS" && decision.decision).slice(0, 3);
  const billingHref = match.series_id ? `/billing?series=${encodeURIComponent(match.series_id)}` : "/billing";
  return (
    <article className={`match-ai-card ${scope ? "has-access" : "is-locked"}`}>
      <PanelHeading kicker="AI INTELLIGENCE" title={locale === "zh-CN" ? "AI 怎么看这场比赛" : "How AI sees this match"} aside={scope ? scopeLabel(scope, locale) : undefined} />
      {scope ? (
        loading ? <div className="match-ai-loading"><span /><span /><span /></div> : successful.length > 0 ? (
          <div className="match-ai-decisions">
            {successful.map((decision) => (
              <div className="match-ai-decision" key={decision.id}>
                <div><strong>{decision.provider}</strong><span>{decision.model}</span></div>
                <b>{actionLabel(decision, match, locale)}</b>
                <em>{confidenceText(decision.decision?.confidence)}</em>
                <p>{decision.decision?.primary_reasons?.[0] || (locale === "zh-CN" ? "暂无可展示的主要理由" : "No primary reason available")}</p>
              </div>
            ))}
          </div>
        ) : <EmptyCardMessage text={locale === "zh-CN" ? "你的权限已生效，但这场比赛暂时还没有成功的 AI 判断。" : "Your access is active, but this match has no successful AI call yet."} />
      ) : (
        <div className="match-ai-lock">
          <span aria-hidden="true">✦</span>
          <h3>{!authEnabled ? (locale === "zh-CN" ? "AI 权限当前不可用" : "AI access is unavailable") : !signedIn ? (locale === "zh-CN" ? "登录后查看 AI 判断" : "Sign in to view AI calls") : (locale === "zh-CN" ? "这场比赛的 AI 判断需要对应权限" : "AI calls for this match require access")}</h3>
          <p>{locale === "zh-CN" ? "赛事、比分、Draft、Live 和市场信息继续公开；付费权限只解锁 AI 决策层。" : "Event, score, Draft, live and market information remain public; paid access unlocks only the AI decision layer."}</p>
          {authEnabled && (!signedIn ? <button className="product-btn product-btn-primary" type="button" onClick={onLogin}>{locale === "zh-CN" ? "登录" : "Sign in"}<span>→</span></button> : <a className="product-btn product-btn-primary" href={billingHref}>{locale === "zh-CN" ? "查看 AI 权益" : "View AI access"}<span>→</span></a>)}
        </div>
      )}
      <p className="match-ai-disclaimer">{locale === "zh-CN" ? "AI 内容用于分析和 Shadow 验证，不代表真实下注执行或收益承诺。" : "AI content is for analysis and Shadow validation, not real betting execution or a promise of returns."}</p>
    </article>
  );
};

const PanelHeading: React.FC<{ kicker: string; title: string; aside?: string }> = ({ kicker, title, aside }) => (
  <div className="match-panel-heading"><div><span className="home-eyebrow">{kicker}</span><h2>{title}</h2></div>{aside ? <em>{aside}</em> : null}</div>
);

const EmptyCardMessage: React.FC<{ text: string }> = ({ text }) => <div className="match-empty-message">{text}</div>;

const PhaseBadge: React.FC<{ phase: MapSummary["phase"]; locale: string }> = ({ phase, locale }) => {
  const key = phase === "LIVE" ? "live" : phase === "PREMATCH" || phase === "UNKNOWN" ? "upcoming" : phase === "AWAITING_RESULT" ? "settling" : "completed";
  const text = phase === "LIVE" ? (locale === "zh-CN" ? "进行中" : "Live") : phase === "PREMATCH" || phase === "UNKNOWN" ? (locale === "zh-CN" ? "未开始" : "Upcoming") : phase === "AWAITING_RESULT" ? (locale === "zh-CN" ? "赛果确认中" : "Confirming result") : (locale === "zh-CN" ? "已结束" : "Final");
  return <span className={`match-phase-badge is-${key}`}><i aria-hidden="true" />{text}</span>;
};

function scoreText(match: MapSummary): string {
  return match.series_score ? `${match.series_score.team_a} : ${match.series_score.team_b}` : "VS";
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

function formatOdds(value: number | string | null | undefined): string {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(2) : "—";
}

function teamInitial(name: string): string {
  return name.trim().split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function winnerName(detail: MapDetail | undefined, match: MapSummary): string | null {
  const winner = detail?.result?.winner_team_id;
  if (!winner) return null;
  if (winner === match.team_a?.id) return match.team_a.name;
  if (winner === match.team_b?.id) return match.team_b.name;
  return null;
}

function latestMarketPair(match: MapSummary): { a: string | null; b: string | null } | null {
  if (!match.market.length) return null;
  const sorted = [...match.market].sort((left, right) => Date.parse(right.received_at) - Date.parse(left.received_at));
  const a = sorted.find((item) => item.selection_team_id === match.team_a?.id);
  const b = sorted.find((item) => item.selection_team_id === match.team_b?.id);
  if (!a && !b) return null;
  return { a: a ? formatOdds(a.price) : null, b: b ? formatOdds(b.price) : null };
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

function netWorthText(value: number | null, match: MapSummary, locale: string): string {
  if (value == null) return locale === "zh-CN" ? "经济领先暂不可用" : "Net worth lead unavailable";
  const team = value >= 0 ? match.team_a?.name : match.team_b?.name;
  const amount = Math.abs(value);
  return locale === "zh-CN" ? `${team || "一方"} 经济领先 ${formatCompactNumber(amount)}` : `${team || "One side"} leads net worth by ${formatCompactNumber(amount)}`;
}

function formatCompactNumber(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

function phaseEmptyText(phase: MapSummary["phase"], locale: string): string {
  if (phase === "PREMATCH" || phase === "UNKNOWN") return locale === "zh-CN" ? "比赛开始后会显示实时进程" : "Live state will appear after the match starts";
  if (phase === "POSTMATCH" || phase === "AWAITING_RESULT") return locale === "zh-CN" ? "这场比赛没有可用的实时快照" : "No live snapshot is available for this match";
  return locale === "zh-CN" ? "正在等待实时数据" : "Waiting for live data";
}

function scopeLabel(scope: Exclude<AiAccessScope, null>, locale: string): string {
  if (locale !== "zh-CN") return scope === "GLOBAL" ? "Pro access" : scope === "SERIES" ? "Series access" : "Map access";
  return scope === "GLOBAL" ? "Pro 权限" : scope === "SERIES" ? "系列赛权限" : "本局权限";
}

function actionLabel(decision: AiDecision, match: MapSummary, locale: string): string {
  const action = decision.decision?.action || "";
  if (action === "BUY_A" || action === "BET_A") return match.team_a?.name || (locale === "zh-CN" ? "队伍 A" : "Team A");
  if (action === "BUY_B" || action === "BET_B") return match.team_b?.name || (locale === "zh-CN" ? "队伍 B" : "Team B");
  if (action === "NO_BUY" || action === "NO_BET" || action === "PASS") return locale === "zh-CN" ? "暂不行动" : "No action";
  return action || (locale === "zh-CN" ? "判断完成" : "Decision ready");
}

function confidenceText(value: number | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
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
