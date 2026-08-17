import React from "react";
import type { MapSummary } from "../api";
import {
  buildEventSummaries,
  buildSeriesSummaries,
  eventHref,
  eventNameFromPath,
  type EventSeriesSummary,
  type EventStatus,
  type EventSummary
} from "../events";
import { useI18n } from "../i18n";

type EventFilter = "ALL" | "LIVE" | "UPCOMING" | "COMPLETED";

interface EventsPageProps {
  matches: MapSummary[];
  loading: boolean;
  pathname: string;
  hasPro: boolean;
}

export const EventsPage: React.FC<EventsPageProps> = ({ matches, loading, pathname, hasPro }) => {
  const { locale } = useI18n();
  const events = React.useMemo(() => buildEventSummaries(matches), [matches]);
  const selectedName = eventNameFromPath(pathname);

  if (selectedName) {
    const selected = events.find((event) => event.name === selectedName) ?? null;
    return <EventDetail event={selected} loading={loading} locale={locale} hasPro={hasPro} />;
  }

  return <EventIndex events={events} loading={loading} locale={locale} />;
};

const EventIndex: React.FC<{ events: EventSummary[]; loading: boolean; locale: string }> = ({
  events,
  loading,
  locale
}) => {
  const [filter, setFilter] = React.useState<EventFilter>("ALL");
  const [query, setQuery] = React.useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = events.filter((event) => {
    const matchesFilter = filter === "ALL" || event.status === filter;
    const matchesQuery = !normalizedQuery || event.name.toLocaleLowerCase().includes(normalizedQuery);
    return matchesFilter && matchesQuery;
  });
  const liveCount = events.filter((event) => event.status === "LIVE").length;
  const upcomingCount = events.filter((event) => event.status === "UPCOMING").length;

  return (
    <div className="events-v2">
      <section className="events-hero product-container">
        <div>
          <span className="home-eyebrow">DOTA EVENTS</span>
          <h1>{locale === "zh-CN" ? "全球 Dota 赛事，一处追踪" : "One place for the Dota events that matter"}</h1>
          <p>
            {locale === "zh-CN"
              ? "先看赛事进度，再进入具体对局。赛程、对阵和赛果保持公开；需要更深的 AI 判断时，再进入对应的 Pro 权益。"
              : "Start with the event, then drill into the match. Schedules, matchups and results stay public; deeper AI intelligence sits behind the relevant Pro access."}
          </p>
        </div>
        <div className="events-hero-stats" aria-label={locale === "zh-CN" ? "赛事概览" : "Event overview"}>
          <EventHeroStat value={events.length} label={locale === "zh-CN" ? "已发现赛事" : "Events"} />
          <EventHeroStat value={liveCount} label={locale === "zh-CN" ? "正在进行" : "Live"} accent />
          <EventHeroStat value={upcomingCount} label={locale === "zh-CN" ? "即将开始" : "Upcoming"} />
        </div>
      </section>

      <section className="product-container events-toolbar" aria-label={locale === "zh-CN" ? "赛事筛选" : "Event filters"}>
        <div className="events-filters" role="group" aria-label={locale === "zh-CN" ? "赛事状态" : "Event status"}>
          {(["ALL", "LIVE", "UPCOMING", "COMPLETED"] as EventFilter[]).map((value) => (
            <button
              key={value}
              type="button"
              className={filter === value ? "is-active" : undefined}
              onClick={() => setFilter(value)}
            >
              {filterLabel(value, locale)}
            </button>
          ))}
        </div>
        <label className="events-search">
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={locale === "zh-CN" ? "搜索赛事" : "Search events"}
            aria-label={locale === "zh-CN" ? "搜索赛事" : "Search events"}
          />
        </label>
      </section>

      <section className="product-container events-directory product-section">
        <div className="events-directory-head">
          <h2>{locale === "zh-CN" ? "赛事列表" : "Event directory"}</h2>
          {!loading && <span>{locale === "zh-CN" ? `${filtered.length} 个结果` : `${filtered.length} results`}</span>}
        </div>
        {loading ? (
          <div className="events-card-grid">
            {[0, 1, 2, 3, 4, 5].map((item) => <div className="event-directory-card is-skeleton" key={item} />)}
          </div>
        ) : filtered.length > 0 ? (
          <div className="events-card-grid">
            {filtered.map((event, index) => <EventDirectoryCard key={event.name} event={event} index={index} locale={locale} />)}
          </div>
        ) : (
          <div className="events-empty">
            <span aria-hidden="true">◇</span>
            <h3>{locale === "zh-CN" ? "没有找到匹配的赛事" : "No matching events"}</h3>
            <p>{locale === "zh-CN" ? "换一个状态或搜索词试试。" : "Try another status or search term."}</p>
          </div>
        )}
      </section>
    </div>
  );
};

const EventDetail: React.FC<{
  event: EventSummary | null;
  loading: boolean;
  locale: string;
  hasPro: boolean;
}> = ({ event, loading, locale, hasPro }) => {
  if (loading) {
    return <div className="product-container event-detail-loading"><div className="event-detail-hero is-skeleton" /></div>;
  }
  if (!event) {
    return (
      <section className="product-container event-not-found">
        <span aria-hidden="true">◇</span>
        <h1>{locale === "zh-CN" ? "没有找到这个赛事" : "Event not found"}</h1>
        <p>{locale === "zh-CN" ? "它可能还没有同步，或者赛事名称已经更新。" : "It may not be synced yet, or the event name may have changed."}</p>
        <a className="product-btn product-btn-primary" href="/events">{locale === "zh-CN" ? "返回赛事列表" : "Back to events"}</a>
      </section>
    );
  }

  const series = buildSeriesSummaries(event);
  const featured = event.matches.find((match) => match.phase === "LIVE") ?? event.nextMatch;
  const stages = groupSeriesByStage(series, locale);

  return (
    <div className="event-detail-v2">
      <section className="product-container event-detail-crumbs">
        <a href="/events">{locale === "zh-CN" ? "赛事" : "Events"}</a><span>›</span><strong>{event.name}</strong>
      </section>

      <section className="product-container event-detail-hero">
        <div className="event-detail-emblem" aria-hidden="true">{eventInitial(event.name)}</div>
        <div className="event-detail-heading">
          <StatusPill status={event.status} locale={locale} />
          <h1>{event.name}</h1>
          <p>{eventDateRange(event, locale)}</p>
        </div>
        <div className="event-detail-stats">
          <EventHeroStat value={event.seriesCount} label={locale === "zh-CN" ? "系列赛" : "Series"} />
          <EventHeroStat value={event.teamCount} label={locale === "zh-CN" ? "参赛队伍" : "Teams"} />
          <EventHeroStat value={event.stages.length || 1} label={locale === "zh-CN" ? "赛段" : "Stages"} />
        </div>
      </section>

      {featured && (
        <section className="product-container event-featured-match product-section">
          <div className="event-featured-kicker">
            <span className={featured.phase === "LIVE" ? "is-live" : undefined} />
            {featured.phase === "LIVE" ? (locale === "zh-CN" ? "正在进行" : "Live now") : (locale === "zh-CN" ? "下一场比赛" : "Next match")}
          </div>
          <div className="event-featured-main">
            <time>{featured.scheduled_at ? formatDateTime(featured.scheduled_at, locale) : "—"}</time>
            <TeamPair match={featured} locale={locale} />
            <div className="event-featured-meta">
              <span>{featured.round || (locale === "zh-CN" ? "赛程" : "Schedule")}</span>
              {featured.best_of ? <span>BO{featured.best_of}</span> : null}
            </div>
            <a className="product-btn product-btn-secondary" href="/match-console">
              {locale === "zh-CN" ? "进入比赛情报" : "Open match intelligence"}<span>→</span>
            </a>
          </div>
        </section>
      )}

      <div className="product-container event-detail-layout product-section">
        <section className="event-schedule-panel">
          <div className="event-panel-title">
            <div><span className="home-eyebrow">MATCHES</span><h2>{locale === "zh-CN" ? "对阵与赛果" : "Matches & results"}</h2></div>
            <span>{locale === "zh-CN" ? `${series.length} 个系列赛` : `${series.length} series`}</span>
          </div>
          {Array.from(stages.entries()).map(([stage, stageSeries]) => (
            <div className="event-stage" key={stage}>
              <div className="event-stage-title"><h3>{stage}</h3><span>{stageSeries.length}</span></div>
              <div className="event-series-list">
                {stageSeries.map((item) => <SeriesRow key={item.seriesId} series={item} locale={locale} />)}
              </div>
            </div>
          ))}
          {series.length === 0 && <div className="events-empty is-compact"><p>{locale === "zh-CN" ? "这个赛事暂时还没有确认的对阵。" : "No confirmed matchups for this event yet."}</p></div>}
        </section>

        <aside className="event-detail-aside">
          <article className="event-access-card">
            <span className="home-eyebrow">ACCESS</span>
            <h2>{locale === "zh-CN" ? "比赛公开，AI 按权限解锁" : "Matches public. AI unlocked by access."}</h2>
            <div className="event-access-row"><i>✓</i><div><strong>{locale === "zh-CN" ? "公开赛事层" : "Public event layer"}</strong><p>{locale === "zh-CN" ? "赛程、对阵、比分、赛果与基础比赛情报无需登录。" : "Schedules, matchups, scores, results and core match intelligence require no sign-in."}</p></div></div>
            <div className="event-access-row is-pro"><i>✦</i><div><strong>{locale === "zh-CN" ? "AI 与实时通知" : "AI & realtime alerts"}</strong><p>{locale === "zh-CN" ? "AI 决策、关键节点通知和完整复盘根据你的 Pro 或赛事权限开放。" : "AI decisions, key-moment alerts and full review open according to your Pro or event access."}</p></div></div>
            <a href="/billing">{hasPro ? (locale === "zh-CN" ? "查看我的 Pro 权益" : "View my Pro access") : (locale === "zh-CN" ? "查看 AI 权益" : "Explore AI access")}<span>→</span></a>
          </article>
          <article className="event-trust-card">
            <span aria-hidden="true">◎</span>
            <div><strong>{locale === "zh-CN" ? "只展示已确认的比赛" : "Confirmed matches only"}</strong><p>{locale === "zh-CN" ? "尚未同步或身份未确认的对阵不会为了填满页面而补写。" : "Unsynced or unconfirmed matchups are not invented just to fill the page."}</p></div>
          </article>
        </aside>
      </div>
    </div>
  );
};

const EventDirectoryCard: React.FC<{ event: EventSummary; index: number; locale: string }> = ({ event, index, locale }) => {
  const focus = event.matches.find((match) => match.phase === "LIVE") ?? event.nextMatch ?? event.latestMatch;
  return (
    <article className={`event-directory-card event-tone-${index % 3}`}>
      <div className="event-directory-top">
        <div className="event-directory-emblem" aria-hidden="true">{eventInitial(event.name)}</div>
        <StatusPill status={event.status} locale={locale} />
      </div>
      <div className="event-directory-copy">
        <h3>{event.name}</h3>
        <p>{event.stages.slice(0, 2).join(" · ") || (locale === "zh-CN" ? "赛事" : "Event")}</p>
      </div>
      <div className="event-directory-numbers">
        <span><strong>{event.seriesCount}</strong>{locale === "zh-CN" ? "系列赛" : "Series"}</span>
        <span><strong>{event.teamCount}</strong>{locale === "zh-CN" ? "队伍" : "Teams"}</span>
      </div>
      {focus ? (
        <div className="event-directory-focus">
          <small>{focus.phase === "LIVE" ? (locale === "zh-CN" ? "正在进行" : "Live") : event.status === "COMPLETED" ? (locale === "zh-CN" ? "最近赛果" : "Latest") : (locale === "zh-CN" ? "下一场" : "Next")}</small>
          <strong>{focus.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD")} <em>vs</em> {focus.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD")}</strong>
          <span>{focus.scheduled_at ? formatDateTime(focus.scheduled_at, locale) : "—"}</span>
        </div>
      ) : <div className="event-directory-focus is-empty">{locale === "zh-CN" ? "等待确认对阵" : "Awaiting confirmed matchup"}</div>}
      <a className="event-directory-link" href={eventHref(event.name)}>{locale === "zh-CN" ? "查看赛事" : "View event"}<span>→</span></a>
    </article>
  );
};

const SeriesRow: React.FC<{ series: EventSeriesSummary; locale: string }> = ({ series, locale }) => {
  const score = series.score;
  const showScore = Boolean(score && (series.phase === "LIVE" || series.phase === "POSTMATCH" || series.phase === "AWAITING_RESULT"));
  return (
    <article className="event-series-row">
      <div className="event-series-time"><time>{series.scheduledAt ? formatDateTime(series.scheduledAt, locale) : "—"}</time><PhasePill phase={series.phase} locale={locale} /></div>
      <div className="event-series-teams">
        <TeamName team={series.teamA} locale={locale} />
        <strong className={showScore ? "is-score" : undefined}>{showScore ? `${score?.team_a ?? 0} : ${score?.team_b ?? 0}` : "VS"}</strong>
        <TeamName team={series.teamB} locale={locale} />
      </div>
      <div className="event-series-meta"><span>{series.bestOf ? `BO${series.bestOf}` : "—"}</span><span>{locale === "zh-CN" ? `${series.mapCount} 局记录` : `${series.mapCount} map records`}</span></div>
      <a href="/match-console">{locale === "zh-CN" ? "比赛情报" : "Match intel"}<span>›</span></a>
    </article>
  );
};

const TeamPair: React.FC<{ match: MapSummary; locale: string }> = ({ match, locale }) => (
  <div className="event-featured-teams">
    <TeamName team={match.team_a} locale={locale} large />
    <strong>{match.series_score ? `${match.series_score.team_a} : ${match.series_score.team_b}` : "VS"}</strong>
    <TeamName team={match.team_b} locale={locale} large />
  </div>
);

const TeamName: React.FC<{ team: MapSummary["team_a"]; locale: string; large?: boolean }> = ({ team, locale, large }) => {
  const name = team?.name || (locale === "zh-CN" ? "待定" : "TBD");
  return <span className={`event-team-name ${large ? "is-large" : ""}`}><i aria-hidden="true">{teamInitial(name)}</i><b>{name}</b></span>;
};

const EventHeroStat: React.FC<{ value: number; label: string; accent?: boolean }> = ({ value, label, accent }) => (
  <div className={accent ? "is-accent" : undefined}><strong>{value}</strong><span>{label}</span></div>
);

const StatusPill: React.FC<{ status: EventStatus; locale: string }> = ({ status, locale }) => (
  <span className={`event-v2-status status-${status.toLowerCase()}`}><i aria-hidden="true" />{statusLabel(status, locale)}</span>
);

const PhasePill: React.FC<{ phase: MapSummary["phase"]; locale: string }> = ({ phase, locale }) => {
  const normalized = phase === "LIVE" ? "live" : phase === "PREMATCH" || phase === "UNKNOWN" ? "upcoming" : phase === "AWAITING_RESULT" ? "settling" : "completed";
  const text = phase === "LIVE"
    ? (locale === "zh-CN" ? "进行中" : "Live")
    : phase === "PREMATCH" || phase === "UNKNOWN"
      ? (locale === "zh-CN" ? "未开始" : "Upcoming")
      : phase === "AWAITING_RESULT"
        ? (locale === "zh-CN" ? "赛果确认中" : "Confirming")
        : (locale === "zh-CN" ? "已结束" : "Final");
  return <span className={`event-series-phase is-${normalized}`}>{text}</span>;
};

function filterLabel(filter: EventFilter, locale: string): string {
  if (locale !== "zh-CN") return filter === "ALL" ? "All" : filter === "LIVE" ? "Live" : filter === "UPCOMING" ? "Upcoming" : "Completed";
  return filter === "ALL" ? "全部" : filter === "LIVE" ? "进行中" : filter === "UPCOMING" ? "即将开始" : "已结束";
}

function statusLabel(status: EventStatus, locale: string): string {
  if (locale !== "zh-CN") return status === "LIVE" ? "Live" : status === "UPCOMING" ? "Upcoming" : status === "SETTLING" ? "Confirming result" : "Completed";
  return status === "LIVE" ? "进行中" : status === "UPCOMING" ? "即将开始" : status === "SETTLING" ? "赛果确认中" : "已结束";
}

function groupSeriesByStage(series: EventSeriesSummary[], locale: string): Map<string, EventSeriesSummary[]> {
  const grouped = new Map<string, EventSeriesSummary[]>();
  for (const item of series) {
    const stage = item.round?.trim() || (locale === "zh-CN" ? "赛程" : "Schedule");
    grouped.set(stage, [...(grouped.get(stage) ?? []), item]);
  }
  return grouped;
}

function eventDateRange(event: EventSummary, locale: string): string {
  if (!event.startsAt && !event.endsAt) return locale === "zh-CN" ? "赛程时间待确认" : "Schedule to be confirmed";
  if (!event.startsAt || !event.endsAt || event.startsAt === event.endsAt) return formatDate(event.startsAt || event.endsAt || "", locale);
  return `${formatDate(event.startsAt, locale)} — ${formatDate(event.endsAt, locale)}`;
}

function formatDate(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}

function formatDateTime(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

function eventInitial(name: string): string {
  const ti = name.match(/TI\s*\d+/i);
  return ti ? ti[0].replace(/\s+/g, "").toUpperCase() : name.replace(/[^A-Za-z0-9\u4e00-\u9fff]/g, "").slice(0, 2).toUpperCase();
}

function teamInitial(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}
