import React from "react";
import type { MapSummary } from "../api";
import { buildEventSummaries, buildSeriesSummaries, eventHref, type EventStatus, type EventSummary } from "../events";
import { useI18n } from "../i18n";
import { isLivePhase, isUpcomingPhase } from "../matchPhase";
import { matchHref } from "../matches";
import { EventMark, TeamCrest, UiIcon } from "./VisualIdentity";

const HOME_HERO_IMAGE = "/assets/heroes/home-hero-aegis.webp";

interface HomePageProps {
  matches: MapSummary[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  signedIn: boolean;
  onLogin: () => void;
}

export const HomePage: React.FC<HomePageProps> = ({
  matches,
  loading,
  error,
  onRetry,
  signedIn,
  onLogin
}) => {
  const { locale } = useI18n();
  const groups = React.useMemo(() => buildEventSummaries(matches), [matches]);
  const series = React.useMemo(() => groups.flatMap((group) => buildSeriesSummaries(group)), [groups]);
  const featuredGroups = groups.filter((group) => group.status !== "COMPLETED").slice(0, 3);
  const upcoming = series
    .filter((item) => isUpcomingPhase(item.phase))
    .map((item) => item.representative)
    .sort(byScheduledAscending)
    .slice(0, 4);
  const completed = series
    .filter((item) => item.phase === "POSTMATCH")
    .map((item) => item.representative)
    .sort(byScheduledDescending)
    .slice(0, 4);
  const currentEventEmptyText = groups.length > 0
    ? locale === "zh-CN"
      ? "目前没有进行中或即将开始的赛事。历史赛事仍可在全部赛事中查看。"
      : "No live or upcoming events right now. Historical events are still available in All events."
    : locale === "zh-CN"
      ? "暂时还没有同步到赛事。数据到达后，进行中和即将开始的赛事会出现在这里。"
      : "No events have synced yet. Live and upcoming events will appear here once data arrives.";

  return (
    <div className="home-v2">
      <section className="home-hero product-container">
        <img className="home-hero-background" src={HOME_HERO_IMAGE} alt="" loading="eager" decoding="async" />
        <div className="home-hero-copy">
          <span className="home-eyebrow">DOTA MATCH INTELLIGENCE</span>
          <h1>{locale === "zh-CN" ? "看懂比赛，验证 AI，追踪真实表现" : "Follow the match. Test the AI. Track real performance."}</h1>
          <p>
            {locale === "zh-CN"
              ? "追踪全球 Dota 赛事和比赛进程，对比 AI 在关键节点的预测，并在赛后用数据验证这些预测的表现。"
              : "Track Dota events and matches, compare AI predictions at key moments, and verify their performance after the match."}
          </p>
          <div className="home-hero-actions">
            <a className="product-btn product-btn-primary" href="/events">{locale === "zh-CN" ? "探索赛事" : "Explore events"}<span>→</span></a>
            <a className="product-btn product-btn-secondary" href="#capabilities">{locale === "zh-CN" ? "了解功能" : "Explore features"}</a>
          </div>
        </div>
        <div className="home-hero-art" aria-hidden="true" />
      </section>

      <section className="product-container product-section" id="current-events" aria-busy={loading}>
        <SectionTitle title={locale === "zh-CN" ? "正在进行与即将开始" : "Live & upcoming events"} action={locale === "zh-CN" ? "全部赛事" : "All events"} href="/events" />
        {loading ? (
          <div className="tournament-grid">{[0, 1, 2].map((item) => <div key={item} className="tournament-card is-skeleton" />)}</div>
        ) : error ? (
          <HomeLoadError locale={locale} onRetry={onRetry} />
        ) : featuredGroups.length > 0 ? (
          <div className={`tournament-grid ${featuredGroups.length === 1 ? "is-single" : ""}`}>
            {featuredGroups.map((group, index) => <TournamentCard key={group.name} group={group} index={index} locale={locale} />)}
          </div>
        ) : (
          <EmptyHomeState text={currentEventEmptyText} />
        )}
      </section>

      <section className="product-container home-match-grid product-section" aria-busy={loading}>
        <div className="home-list-card">
          <SectionTitle title={locale === "zh-CN" ? "即将开始的比赛" : "Upcoming matches"} action={locale === "zh-CN" ? "查看赛事" : "View events"} href="/events" compact />
          <div className="home-match-list">
            {loading
              ? <HomeListSkeleton />
              : error
                ? <ListLoadError locale={locale} onRetry={onRetry} />
                : upcoming.length > 0
                  ? upcoming.map((match) => <MatchRow key={match.id} match={match} mode="upcoming" locale={locale} />)
                  : <ListEmpty text={locale === "zh-CN" ? "目前没有即将开始的比赛" : "No upcoming matches right now"} />}
          </div>
        </div>
        <div className="home-list-card">
          <SectionTitle title={locale === "zh-CN" ? "最近结束的比赛" : "Recent results"} action={locale === "zh-CN" ? "查看赛事结果" : "View event results"} href="/events" compact />
          <div className="home-match-list">
            {loading
              ? <HomeListSkeleton />
              : error
                ? <ListLoadError locale={locale} onRetry={onRetry} />
                : completed.length > 0
                  ? completed.map((match) => <MatchRow key={match.id} match={match} mode="completed" locale={locale} />)
                  : <ListEmpty text={locale === "zh-CN" ? "还没有已完成的比赛" : "No completed matches yet"} />}
          </div>
        </div>
      </section>

      <section className="product-container product-section home-capabilities" id="capabilities">
        <article><span className="capability-icon radar-icon"><UiIcon name="clock" size={19} /></span><div><h3>{locale === "zh-CN" ? "比赛追踪" : "Match tracking"}</h3><p>{locale === "zh-CN" ? "赛程、比分、Draft、Live 数据和赛果都放在同一条比赛线上。" : "Schedule, score, Draft, live data and results in one match flow."}</p></div><a href="/events" aria-label={locale === "zh-CN" ? "进入比赛追踪" : "Open match tracking"}>›</a></article>
        <article><span className="capability-icon ai-icon"><UiIcon name="spark" size={19} /></span><div><h3>{locale === "zh-CN" ? "AI 预测对比" : "AI prediction comparison"}</h3><p>{locale === "zh-CN" ? "查看不同模型在关键节点预测哪一方，以及它们为什么做出不同选择。" : "Compare which side each model predicts at key moments and why they disagree."}</p></div><a href="/review" aria-label={locale === "zh-CN" ? "查看 AI 预测" : "See AI predictions"}>›</a></article>
        <article><span className="capability-icon shadow-icon"><UiIcon name="layers" size={19} /></span><div><h3>{locale === "zh-CN" ? "积分表现复盘" : "Points performance"}</h3><p>{locale === "zh-CN" ? "用统一的预测积分规则回看长期表现，并结合命中率、Brier 与样本量比较模型。" : "Review long-run performance under one prediction-points rule, together with hit rate, Brier score, and sample size."}</p></div><a href="/performance" aria-label={locale === "zh-CN" ? "查看积分排行" : "See points leaderboard"}>›</a></article>
      </section>

      <section className="product-container home-access-banner product-section">
        <div className="home-access-icon" aria-hidden="true"><UiIcon name="spark" size={24} /></div>
        <div><h2>{locale === "zh-CN" ? "先体验，再解锁你关心的比赛" : "Start free, then unlock the matches you follow"}</h2><p>{locale === "zh-CN" ? "小组赛 AI、积分表现和复盘免费开放；付费阶段进行中的完整 AI 预测与实时通知需要 Pass，确认赛果后基础预测公开。" : "Group-stage AI, points performance, and review are free. Full live predictions and alerts for paid stages require a Pass; core predictions become public after the result is confirmed."}</p></div>
        {signedIn ? <a className="product-btn access-btn" href="/billing">{locale === "zh-CN" ? "查看赛事 Pass" : "View competition passes"}<span>→</span></a> : <button className="product-btn access-btn" type="button" onClick={onLogin}>{locale === "zh-CN" ? "登录后查看 Pass" : "Sign in to view passes"}<span>→</span></button>}
      </section>
    </div>
  );
};

const SectionTitle: React.FC<{ title: string; action: string; href: string; compact?: boolean }> = ({ title, action, href, compact }) => <div className={`product-section-title ${compact ? "is-compact" : ""}`}><h2>{title}</h2><a href={href}>{action}<span>→</span></a></div>;

const TournamentCard: React.FC<{ group: EventSummary; index: number; locale: string }> = ({ group, index, locale }) => {
  const stage = group.stages[0] || (locale === "zh-CN" ? "赛事" : "Event");
  const nextAt = group.nextMatch?.scheduled_at ? formatTime(group.nextMatch.scheduled_at, locale) : null;
  const focus = group.matches.find((match) => isLivePhase(match.phase)) ?? group.nextMatch;
  return <article className={`tournament-card event-tone-${index % 3}`}><div className="event-emblem event-emblem-rich"><EventMark eventName={group.name} size="md" /></div><div className="event-card-body"><div className="event-card-title"><h3>{group.name}</h3><StatusPill status={group.status} locale={locale} /></div><p>{stage}</p><div className="event-card-meta"><span><UiIcon name="trophy" size={11} />{group.seriesCount} {locale === "zh-CN" ? "个系列赛" : "series"}</span>{nextAt && <span><UiIcon name="clock" size={11} />{locale === "zh-CN" ? "下一场" : "Next"} {nextAt}</span>}</div></div>{focus && <div className="event-card-focus"><small>{isLivePhase(focus.phase) ? (locale === "zh-CN" ? "正在进行" : "Live now") : (locale === "zh-CN" ? "下一场对阵" : "Next matchup")}</small><div><span><TeamCrest team={focus.team_a} fallbackName={focus.team_a?.name} size="sm" />{focus.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD")}</span><b>{focus.series_score && isLivePhase(focus.phase) ? `${focus.series_score.team_a} : ${focus.series_score.team_b}` : "VS"}</b><span><TeamCrest team={focus.team_b} fallbackName={focus.team_b?.name} size="sm" />{focus.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD")}</span></div></div>}<a className="event-card-action" href={eventHref(group.name)}>{locale === "zh-CN" ? "查看赛事" : "View event"}<span>›</span></a></article>;
};

const MatchRow: React.FC<{ match: MapSummary; mode: "upcoming" | "completed"; locale: string }> = ({ match, mode, locale }) => {
  const a = match.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const b = match.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const score = match.series_score ? `${match.series_score.team_a} - ${match.series_score.team_b}` : mode === "completed" ? (locale === "zh-CN" ? "已结束" : "Final") : "vs";
  const delayed = match.phase === "DELAYED_START";
  return <div className={`home-match-row ${delayed ? "is-delayed" : ""}`}><time><span><UiIcon name="clock" size={11} />{delayed ? (locale === "zh-CN" ? "顺延中" : "Delayed") : match.scheduled_at ? formatTime(match.scheduled_at, locale) : "—"}</span>{delayed && <em>{locale === "zh-CN" ? "原定" : "Scheduled"} {match.scheduled_at ? formatTime(match.scheduled_at, locale) : "—"}</em>}</time><div className="match-teams"><span><TeamCrest team={match.team_a} fallbackName={a} size="sm" />{a}</span><b>{score}</b><span><TeamCrest team={match.team_b} fallbackName={b} size="sm" />{b}</span></div><small>{match.best_of ? `BO${match.best_of}` : match.round || "—"}</small><a href={matchHref(match)}>{locale === "zh-CN" ? "查看比赛" : "View match"}</a></div>;
};

const StatusPill: React.FC<{ status: EventStatus; locale: string }> = ({ status, locale }) => <span className={`event-status status-${status.toLowerCase()}`}>{status === "LIVE" ? (locale === "zh-CN" ? "进行中" : "Live") : status === "UPCOMING" ? (locale === "zh-CN" ? "即将开始" : "Upcoming") : status === "SETTLING" ? (locale === "zh-CN" ? "赛果确认中" : "Confirming") : (locale === "zh-CN" ? "已结束" : "Finished")}</span>;
const ListEmpty: React.FC<{ text: string }> = ({ text }) => <div className="home-list-empty">{text}</div>;
const EmptyHomeState: React.FC<{ text: string }> = ({ text }) => <div className="home-empty-state"><span aria-hidden="true">◇</span><p>{text}</p></div>;
const HomeListSkeleton = () => <div className="home-list-skeleton" aria-label="loading"><span /><span /><span /></div>;
const HomeLoadError: React.FC<{ locale: string; onRetry: () => void }> = ({ locale, onRetry }) => <div className="home-load-error" role="alert"><div><strong>{locale === "zh-CN" ? "赛事数据暂时不可用" : "Event data is temporarily unavailable"}</strong><p>{locale === "zh-CN" ? "保留当前页面，你可以立即重试。" : "Stay on this page and try again now."}</p></div><button className="product-btn product-btn-secondary" type="button" onClick={onRetry}>{locale === "zh-CN" ? "重试" : "Retry"}</button></div>;
const ListLoadError: React.FC<{ locale: string; onRetry: () => void }> = ({ locale, onRetry }) => <div className="home-list-error" role="alert"><span>{locale === "zh-CN" ? "加载失败" : "Failed to load"}</span><button type="button" onClick={onRetry}>{locale === "zh-CN" ? "重试" : "Retry"}</button></div>;

function byScheduledAscending(a: MapSummary, b: MapSummary): number { return byNullableDate(a.scheduled_at, b.scheduled_at); }
function byScheduledDescending(a: MapSummary, b: MapSummary): number { return byNullableDate(b.scheduled_at, a.scheduled_at); }
function byNullableDate(a: string | null | undefined, b: string | null | undefined): number { if (!a && !b) return 0; if (!a) return 1; if (!b) return -1; return new Date(a).getTime() - new Date(b).getTime(); }
function formatTime(value: string, locale: string): string { return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
