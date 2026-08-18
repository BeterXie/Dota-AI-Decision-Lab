import React from "react";
import type { MapSummary } from "../api";
import { buildEventSummaries, buildSeriesSummaries, eventHref, type EventStatus, type EventSummary } from "../events";
import { useI18n } from "../i18n";
import { matchHref } from "../matches";
import { EventMark, TeamCrest, UiIcon } from "./VisualIdentity";

const HOME_HERO_IMAGE = "/assets/heroes/home-hero-aegis.webp";

interface HomePageProps {
  matches: MapSummary[];
  loading: boolean;
  signedIn: boolean;
  onLogin: () => void;
}

export const HomePage: React.FC<HomePageProps> = ({
  matches,
  loading,
  signedIn,
  onLogin
}) => {
  const { locale } = useI18n();
  const groups = React.useMemo(() => buildEventSummaries(matches), [matches]);
  const series = React.useMemo(() => groups.flatMap((group) => buildSeriesSummaries(group)), [groups]);
  const featuredGroups = groups.filter((group) => group.status !== "COMPLETED").slice(0, 3);
  const upcoming = series
    .filter((item) => item.phase === "PREMATCH" || item.phase === "UNKNOWN")
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
              ? "追踪全球 Dota 赛事和比赛进程，对比 AI 在关键节点的判断，并在赛后用数据验证这些决策到底表现如何。"
              : "Track Dota events and matches, compare AI calls at key moments, and verify after the match which decisions actually held up."}
          </p>
          <div className="home-hero-actions">
            <a className="product-btn product-btn-primary" href="/events">{locale === "zh-CN" ? "探索赛事" : "Explore events"}<span>→</span></a>
            <a className="product-btn product-btn-secondary" href="#capabilities">{locale === "zh-CN" ? "了解功能" : "Explore features"}</a>
          </div>
        </div>
        <div className="home-hero-art" aria-hidden="true" />
      </section>

      <section className="product-container product-section" id="current-events">
        <SectionTitle title={locale === "zh-CN" ? "正在进行与即将开始" : "Live & upcoming events"} action={locale === "zh-CN" ? "全部赛事" : "All events"} href="/events" />
        {loading ? (
          <div className="tournament-grid">{[0, 1, 2].map((item) => <div key={item} className="tournament-card is-skeleton" />)}</div>
        ) : featuredGroups.length > 0 ? (
          <div className="tournament-grid">
            {featuredGroups.map((group, index) => <TournamentCard key={group.name} group={group} index={index} locale={locale} />)}
          </div>
        ) : (
          <EmptyHomeState text={currentEventEmptyText} />
        )}
      </section>

      <section className="product-container home-match-grid product-section">
        <div className="home-list-card">
          <SectionTitle title={locale === "zh-CN" ? "即将开始的比赛" : "Upcoming matches"} action={locale === "zh-CN" ? "查看赛事" : "View events"} href="/events" compact />
          <div className="home-match-list">
            {upcoming.length > 0 ? upcoming.map((match) => <MatchRow key={match.id} match={match} mode="upcoming" locale={locale} />) : <ListEmpty text={locale === "zh-CN" ? "目前没有即将开始的比赛" : "No upcoming matches right now"} />}
          </div>
        </div>
        <div className="home-list-card">
          <SectionTitle title={locale === "zh-CN" ? "最近结束的比赛" : "Recent results"} action={locale === "zh-CN" ? "查看赛事结果" : "View event results"} href="/events" compact />
          <div className="home-match-list">
            {completed.length > 0 ? completed.map((match) => <MatchRow key={match.id} match={match} mode="completed" locale={locale} />) : <ListEmpty text={locale === "zh-CN" ? "还没有已完成的比赛" : "No completed matches yet"} />}
          </div>
        </div>
      </section>

      <section className="product-container product-section home-capabilities" id="capabilities">
        <article><span className="capability-icon radar-icon"><UiIcon name="clock" size={19} /></span><div><h3>{locale === "zh-CN" ? "比赛追踪" : "Match tracking"}</h3><p>{locale === "zh-CN" ? "赛程、比分、Draft、Live 数据和赛果都放在同一条比赛线上。" : "Schedule, score, Draft, live data and results in one match flow."}</p></div><a href="/events" aria-label={locale === "zh-CN" ? "进入比赛追踪" : "Open match tracking"}>›</a></article>
        <article><span className="capability-icon ai-icon"><UiIcon name="spark" size={19} /></span><div><h3>{locale === "zh-CN" ? "AI 决策对比" : "AI decision comparison"}</h3><p>{locale === "zh-CN" ? "查看不同模型在关键节点怎么判断，以及它们为什么做出不同选择。" : "Compare what models called at key moments and why they disagreed."}</p></div><a href="/review" aria-label={locale === "zh-CN" ? "查看 AI 决策" : "See AI decisions"}>›</a></article>
        <article><span className="capability-icon shadow-icon"><UiIcon name="layers" size={19} /></span><div><h3>{locale === "zh-CN" ? "Shadow 表现复盘" : "Shadow performance"}</h3><p>{locale === "zh-CN" ? "用相同模拟规则回看长期表现，不把模拟结果包装成真实收益。" : "Review long-run results under the same simulation rules without presenting them as real returns."}</p></div><a href="/performance" aria-label={locale === "zh-CN" ? "查看 AI 表现" : "See AI performance"}>›</a></article>
      </section>

      <section className="product-container home-access-banner product-section">
        <div className="home-access-icon" aria-hidden="true"><UiIcon name="spark" size={24} /></div>
        <div><h2>{locale === "zh-CN" ? "先体验，再解锁你关心的比赛" : "Start free, then unlock the matches you follow"}</h2><p>{locale === "zh-CN" ? "小组赛 AI 决策、AI 表现和复盘免费开放；付费阶段的 AI 决策与实时通知按赛事或系列赛 Pass 解锁。" : "Group-stage AI decisions, AI Performance and Review are free; paid-stage AI and realtime alerts unlock with an Event or Series Pass."}</p></div>
        {signedIn ? <a className="product-btn access-btn" href="/billing">{locale === "zh-CN" ? "查看赛事 Pass" : "View competition passes"}<span>→</span></a> : <button className="product-btn access-btn" type="button" onClick={onLogin}>{locale === "zh-CN" ? "登录后查看 Pass" : "Sign in to view passes"}<span>→</span></button>}
      </section>
    </div>
  );
};

const SectionTitle: React.FC<{ title: string; action: string; href: string; compact?: boolean }> = ({ title, action, href, compact }) => <div className={`product-section-title ${compact ? "is-compact" : ""}`}><h2>{title}</h2><a href={href}>{action}<span>→</span></a></div>;

const TournamentCard: React.FC<{ group: EventSummary; index: number; locale: string }> = ({ group, index, locale }) => {
  const stage = group.stages[0] || (locale === "zh-CN" ? "赛事" : "Event");
  const nextAt = group.nextMatch?.scheduled_at ? formatTime(group.nextMatch.scheduled_at, locale) : null;
  return <article className={`tournament-card event-tone-${index % 3}`}><div className="event-emblem event-emblem-rich"><EventMark eventName={group.name} size="md" /></div><div className="event-card-body"><div className="event-card-title"><h3>{group.name}</h3><StatusPill status={group.status} locale={locale} /></div><p>{stage}</p><div className="event-card-meta"><span><UiIcon name="trophy" size={11} />{group.seriesCount} {locale === "zh-CN" ? "个系列赛" : "series"}</span>{nextAt && <span><UiIcon name="clock" size={11} />{locale === "zh-CN" ? "下一场" : "Next"} {nextAt}</span>}</div></div><a className="event-card-action" href={eventHref(group.name)}>{locale === "zh-CN" ? "查看赛事" : "View event"}<span>›</span></a></article>;
};

const MatchRow: React.FC<{ match: MapSummary; mode: "upcoming" | "completed"; locale: string }> = ({ match, mode, locale }) => {
  const a = match.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const b = match.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const score = match.series_score ? `${match.series_score.team_a} - ${match.series_score.team_b}` : mode === "completed" ? (locale === "zh-CN" ? "已结束" : "Final") : "vs";
  return <div className="home-match-row"><time><UiIcon name="clock" size={11} />{match.scheduled_at ? formatTime(match.scheduled_at, locale) : "—"}</time><div className="match-teams"><span><TeamCrest team={match.team_a} fallbackName={a} size="sm" />{a}</span><b>{score}</b><span><TeamCrest team={match.team_b} fallbackName={b} size="sm" />{b}</span></div><small>{match.best_of ? `BO${match.best_of}` : match.round || "—"}</small><a href={matchHref(match)}>{locale === "zh-CN" ? "查看比赛" : "View match"}</a></div>;
};

const StatusPill: React.FC<{ status: EventStatus; locale: string }> = ({ status, locale }) => <span className={`event-status status-${status.toLowerCase()}`}>{status === "LIVE" ? (locale === "zh-CN" ? "进行中" : "Live") : status === "UPCOMING" ? (locale === "zh-CN" ? "即将开始" : "Upcoming") : status === "SETTLING" ? (locale === "zh-CN" ? "赛果确认中" : "Confirming") : (locale === "zh-CN" ? "已结束" : "Finished")}</span>;
const ListEmpty: React.FC<{ text: string }> = ({ text }) => <div className="home-list-empty">{text}</div>;
const EmptyHomeState: React.FC<{ text: string }> = ({ text }) => <div className="home-empty-state"><span aria-hidden="true">◇</span><p>{text}</p></div>;

function byScheduledAscending(a: MapSummary, b: MapSummary): number { return byNullableDate(a.scheduled_at, b.scheduled_at); }
function byScheduledDescending(a: MapSummary, b: MapSummary): number { return byNullableDate(b.scheduled_at, a.scheduled_at); }
function byNullableDate(a: string | null | undefined, b: string | null | undefined): number { if (!a && !b) return 0; if (!a) return 1; if (!b) return -1; return new Date(a).getTime() - new Date(b).getTime(); }
function formatTime(value: string, locale: string): string { return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
