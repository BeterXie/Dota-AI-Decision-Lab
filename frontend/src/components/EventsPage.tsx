import React from "react";
import type { MapSummary } from "../api";
import {
  buildEventSummaries,
  buildSeriesSummaries,
  eventHref,
  eventNameFromPath,
  eventSlug,
  type EventSeriesSummary,
  type EventStatus,
  type EventSummary
} from "../events";
import { useI18n } from "../i18n";
import { isLivePhase, isUpcomingPhase } from "../matchPhase";
import { matchHref } from "../matches";
import { matchPhaseBadgePresentation } from "../utils/presentation";
import { EventMark, TeamCrest, UiIcon } from "./VisualIdentity";

type EventFilter = "ALL" | "LIVE" | "UPCOMING" | "COMPLETED";
type EventDetailTab = "OVERVIEW" | "SCHEDULE" | "UPCOMING" | "LIVE" | "COMPLETED";

interface EventsPageProps {
  matches: MapSummary[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  pathname: string;
}

export const EventsPage: React.FC<EventsPageProps> = ({ matches, loading, error, onRetry, pathname }) => {
  const { locale } = useI18n();
  const events = React.useMemo(() => buildEventSummaries(matches), [matches]);
  const selectedKey = eventNameFromPath(pathname);

  if (selectedKey) {
    const selected = events.find(
      (event) => event.name === selectedKey || eventSlug(event.name) === selectedKey
    ) ?? null;
    return <EventDetail event={selected} loading={loading} error={error} onRetry={onRetry} locale={locale} />;
  }

  return <EventIndex events={events} loading={loading} error={error} onRetry={onRetry} locale={locale} />;
};

const EventIndex: React.FC<{ events: EventSummary[]; loading: boolean; error: boolean; onRetry: () => void; locale: string }> = ({
  events,
  loading,
  error,
  onRetry,
  locale
}) => {
  const [filter, setFilter] = React.useState<EventFilter>("ALL");
  const [query, setQuery] = React.useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = events.filter((event) => {
    const matchesFilter = filter === "ALL" || event.status === filter || (filter === "COMPLETED" && event.status === "SETTLING");
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
              ? "先看赛事进度，再进入具体对局。赛程、对阵、赛果和确认赛果后的基础 AI 预测公开；付费阶段进行中的完整 AI 预测与实时通知需要 Pass。"
              : "Start with the event, then drill into the match. Schedules, matchups, results, and confirmed post-match core AI predictions are public; full live paid-stage predictions and alerts require a Pass."}
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
        ) : error ? (
          <EventLoadError locale={locale} onRetry={onRetry} />
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
  error: boolean;
  onRetry: () => void;
  locale: string;
}> = ({ event, loading, error, onRetry, locale }) => {
  const [activeTab, setActiveTab] = React.useState<EventDetailTab>("OVERVIEW");
  const [followed, setFollowed] = React.useState(false);

  React.useEffect(() => {
    if (!event || typeof window === "undefined") return;
    setFollowed(window.localStorage.getItem(`followed-event:${eventSlug(event.name)}`) === "1");
  }, [event]);

  if (loading) {
    return <div className="product-container event-detail-loading"><div className="event-detail-hero is-skeleton" /></div>;
  }
  if (error) {
    return <EventLoadError locale={locale} onRetry={onRetry} />;
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
  const visibleSeries = filterEventSeries(series, activeTab);
  const featured = event.matches.find((match) => match.phase === "LIVE")
    ?? event.matches.find((match) => match.phase === "LIVE_DATA_DELAYED")
    ?? event.nextMatch;
  const stages = groupSeriesByStage(visibleSeries, locale);
  const teams = eventTeams(event);
  const completedSeries = series.filter((item) => item.phase === "POSTMATCH").length;
  const isTi15 = event.name === "The International 2026";
  const toggleFollow = () => {
    const next = !followed;
    setFollowed(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(`followed-event:${eventSlug(event.name)}`, next ? "1" : "0");
    }
  };

  return (
    <div className="event-detail-v2">
      <section className="product-container event-detail-crumbs">
        <a href="/events">{locale === "zh-CN" ? "赛事" : "Events"}</a><span>›</span><strong>{event.name}</strong>
      </section>

      <section className={`product-container event-detail-hero${isTi15 ? " is-ti15" : ""}`}>
        {isTi15 ? <img className="event-detail-hero-background" src="/assets/heroes/event-ti15-hero.webp" alt="" loading="eager" decoding="async" /> : null}
        <div className="event-detail-emblem event-detail-emblem-rich">
          <EventMark eventName={event.name} size="lg" />
        </div>
        <div className="event-detail-heading">
          <StatusPill status={event.status} locale={locale} />
          <h1>{event.name}</h1>
          <p><UiIcon name="calendar" size={12} />{eventDateRange(event, locale)}</p>
        </div>
        <button
          type="button"
          className={`event-follow-button ${followed ? "is-followed" : ""}`}
          aria-pressed={followed}
          title={locale === "zh-CN" ? "保存在此浏览器" : "Saved in this browser"}
          onClick={toggleFollow}
        >
          <span aria-hidden="true">{followed ? "★" : "☆"}</span>
          {followed ? (locale === "zh-CN" ? "已收藏" : "Saved") : (locale === "zh-CN" ? "收藏" : "Save")}
        </button>
        <div className="event-detail-stats">
          <EventHeroStat value={event.seriesCount} label={locale === "zh-CN" ? "系列赛" : "Series"} />
          <EventHeroStat value={event.teamCount} label={locale === "zh-CN" ? "参赛队伍" : "Teams"} />
          <EventHeroStat value={event.stages.length || 1} label={locale === "zh-CN" ? "赛段" : "Stages"} />
        </div>
      </section>

      <nav className="product-container event-detail-tabs" aria-label={locale === "zh-CN" ? "赛事详情" : "Event detail"}>
        {(["OVERVIEW", "SCHEDULE", "UPCOMING", "LIVE", "COMPLETED"] as EventDetailTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            className={activeTab === tab ? "is-active" : undefined}
            aria-pressed={activeTab === tab}
            onClick={() => setActiveTab(tab)}
          >
            {eventTabLabel(tab, locale)}
          </button>
        ))}
        <a href="/review">{locale === "zh-CN" ? "AI 复盘" : "AI review"}</a>
      </nav>

      {featured && activeTab === "OVERVIEW" && (
        <section className="product-container event-featured-match product-section">
          <div className="event-featured-kicker">
            <span className={isLivePhase(featured.phase) ? "is-live" : undefined} />
            {featured.phase === "LIVE_DATA_DELAYED"
              ? (locale === "zh-CN" ? "实时数据延迟" : "Live data delayed")
              : featured.phase === "LIVE"
                ? (locale === "zh-CN" ? "正在进行" : "Live now")
                : featured.phase === "DELAYED_START"
                  ? (locale === "zh-CN" ? "赛程延迟" : "Start delayed")
                  : (locale === "zh-CN" ? "下一场比赛" : "Next match")}
          </div>
          <div className="event-featured-main">
            <time><UiIcon name="clock" size={12} />{featured.scheduled_at ? formatDateTime(featured.scheduled_at, locale) : "—"}</time>
            <TeamPair match={featured} locale={locale} />
            <div className="event-featured-meta">
              <span><UiIcon name="layers" size={11} />{featured.round || (locale === "zh-CN" ? "赛程" : "Schedule")}</span>
              {featured.best_of ? <span><UiIcon name="trophy" size={11} />BO{featured.best_of}</span> : null}
            </div>
            <a className="product-btn product-btn-secondary" href={matchHref(featured)}>
              {locale === "zh-CN" ? "查看比赛" : "View match"}<span>→</span>
            </a>
          </div>
        </section>
      )}

      <div className="product-container event-detail-layout product-section">
        <section className="event-schedule-panel">
          <div className="event-panel-title">
            <div><span className="home-eyebrow">MATCHES</span><h2>{eventScheduleTitle(activeTab, locale)}</h2></div>
            <span>{locale === "zh-CN" ? `${visibleSeries.length} 个系列赛` : `${visibleSeries.length} series`}</span>
          </div>
          {Array.from(stages.entries()).map(([stage, stageSeries]) => (
            <div className="event-stage" key={stage}>
              <div className="event-stage-title"><h3>{stage}</h3><span>{stageSeries.length}</span></div>
              <div className="event-series-list">
                {stageSeries.map((item) => <SeriesRow key={item.seriesId} series={item} locale={locale} />)}
              </div>
            </div>
          ))}
          {visibleSeries.length === 0 && <div className="events-empty is-compact"><p>{locale === "zh-CN" ? "这个分类暂时没有确认的对阵。" : "No confirmed matchups in this category yet."}</p></div>}
        </section>

        <aside className="event-detail-aside">
          <article className="event-overview-card">
            <div className="event-aside-title"><span aria-hidden="true">▣</span><h2>{locale === "zh-CN" ? "赛事概览" : "Event overview"}</h2></div>
            <div className="event-overview-grid">
              <EventOverviewMetric label={locale === "zh-CN" ? "比赛阶段" : "Status"} value={statusLabel(event.status, locale)} />
              <EventOverviewMetric label={locale === "zh-CN" ? "已完成" : "Completed"} value={`${completedSeries} / ${series.length}`} />
              <EventOverviewMetric label={locale === "zh-CN" ? "参赛队伍" : "Teams"} value={`${event.teamCount}`} />
              <EventOverviewMetric label={locale === "zh-CN" ? "赛段" : "Stages"} value={`${event.stages.length || 1}`} />
              <EventOverviewMetric label={locale === "zh-CN" ? "主要赛制" : "Formats"} value={seriesFormats(series)} />
              <EventOverviewMetric label={locale === "zh-CN" ? "比赛记录" : "Map records"} value={`${event.matches.length}`} />
            </div>
          </article>
          <article className="event-team-card">
            <div className="event-aside-title"><span aria-hidden="true">♙</span><div><h2>{locale === "zh-CN" ? "参赛队伍" : "Participating teams"}</h2><small>{locale === "zh-CN" ? `${teams.length} 支队伍` : `${teams.length} teams`}</small></div></div>
            <div className="event-team-rail">
              {teams.slice(0, 8).map((team) => <TeamCrest key={team.id || team.name} team={team} fallbackName={team.name} size="md" />)}
              {teams.length > 8 && <span className="event-team-more">+{teams.length - 8}</span>}
            </div>
          </article>
          <article className="event-access-card">
            <span className="home-eyebrow">ACCESS</span>
            <h2>{locale === "zh-CN" ? "比赛公开，AI 按权限解锁" : "Matches public. AI unlocked by access."}</h2>
            <div className="event-access-row"><i>✓</i><div><strong>{locale === "zh-CN" ? "公开赛事层" : "Public event layer"}</strong><p>{locale === "zh-CN" ? "赛程、对阵、比分、赛果与基础比赛情报无需登录。" : "Schedules, matchups, scores, results and core match intelligence require no sign-in."}</p></div></div>
            <div className="event-access-row is-pro"><i>✦</i><div><strong>{locale === "zh-CN" ? "进行中的完整 AI 预测与实时通知" : "Full live AI predictions & realtime alerts"}</strong><p>{locale === "zh-CN" ? "小组赛和确认赛果后的基础 AI 预测公开；付费阶段进行中的完整预测与通知按赛事或系列赛 Pass 解锁。" : "Group-stage and confirmed post-match core AI predictions are public; full live paid-stage predictions and alerts unlock by Event or Series Pass."}</p></div></div>
            <a href={event.canonicalEventId ? `/billing?event=${encodeURIComponent(event.canonicalEventId)}` : "/billing"}>{locale === "zh-CN" ? "查看赛事 Pass" : "View Event Pass"}<span>→</span></a>
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
  const focus = event.matches.find((match) => match.phase === "LIVE")
    ?? event.matches.find((match) => match.phase === "LIVE_DATA_DELAYED")
    ?? event.nextMatch
    ?? event.latestMatch;
  return (
    <article className={`event-directory-card event-tone-${index % 3}`}>
      <div className="event-directory-top">
        <div className="event-directory-emblem event-directory-emblem-rich"><EventMark eventName={event.name} size="md" /></div>
        <StatusPill status={event.status} locale={locale} />
      </div>
      <div className="event-directory-copy">
        <h3>{event.name}</h3>
        <p>{event.stages.slice(0, 2).join(" · ") || (locale === "zh-CN" ? "赛事" : "Event")}</p>
      </div>
      <div className="event-directory-numbers">
        <span><UiIcon name="trophy" size={11} /><strong>{event.seriesCount}</strong>{locale === "zh-CN" ? "系列赛" : "Series"}</span>
        <span><UiIcon name="users" size={11} /><strong>{event.teamCount}</strong>{locale === "zh-CN" ? "队伍" : "Teams"}</span>
      </div>
      {focus ? (
        <div className="event-directory-focus">
          <small>{focus.phase === "LIVE_DATA_DELAYED"
            ? (locale === "zh-CN" ? "实时数据延迟" : "Live data delayed")
            : focus.phase === "LIVE"
              ? (locale === "zh-CN" ? "正在进行" : "Live")
              : focus.phase === "DELAYED_START"
                ? (locale === "zh-CN" ? "赛程延迟" : "Start delayed")
                : event.status === "COMPLETED"
                  ? (locale === "zh-CN" ? "最近赛果" : "Latest")
                  : (locale === "zh-CN" ? "下一场" : "Next")}</small>
          <strong><TeamCrest team={focus.team_a} fallbackName={focus.team_a?.name} size="sm" />{focus.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD")} <em>vs</em> <TeamCrest team={focus.team_b} fallbackName={focus.team_b?.name} size="sm" />{focus.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD")}</strong>
          <span><UiIcon name="clock" size={10} />{focus.scheduled_at ? formatDateTime(focus.scheduled_at, locale) : "—"}</span>
        </div>
      ) : <div className="event-directory-focus is-empty">{locale === "zh-CN" ? "等待确认对阵" : "Awaiting confirmed matchup"}</div>}
      <a className="event-directory-link" href={eventHref(event.name)}>{locale === "zh-CN" ? "查看赛事" : "View event"}<span>→</span></a>
    </article>
  );
};

const SeriesRow: React.FC<{ series: EventSeriesSummary; locale: string }> = ({ series, locale }) => {
  const score = series.score;
  const showScore = Boolean(score && (isLivePhase(series.phase) || series.phase === "POSTMATCH" || series.phase === "AWAITING_RESULT"));
  return (
    <article className="event-series-row">
      <div className="event-series-time"><time><UiIcon name="clock" size={10} />{series.scheduledAt ? formatDateTime(series.scheduledAt, locale) : "—"}</time><PhasePill phase={series.phase} locale={locale} /></div>
      <div className="event-series-teams">
        <TeamName team={series.teamA} locale={locale} />
        <strong className={showScore ? "is-score" : undefined}>{showScore ? `${score?.team_a ?? 0} : ${score?.team_b ?? 0}` : "VS"}</strong>
        <TeamName team={series.teamB} locale={locale} />
      </div>
      <div className="event-series-meta"><span>{series.bestOf ? `BO${series.bestOf}` : "—"}</span><span>{locale === "zh-CN" ? `${series.mapCount} 局记录` : `${series.mapCount} map records`}</span></div>
      <a href={matchHref(series.representative)}>{locale === "zh-CN" ? "查看比赛" : "View match"}<span>›</span></a>
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
  return <span className={`event-team-name ${large ? "is-large" : ""}`}><TeamCrest team={team} fallbackName={name} size={large ? "md" : "sm"} /><b>{name}</b></span>;
};

const EventHeroStat: React.FC<{ value: number; label: string; accent?: boolean }> = ({ value, label, accent }) => (
  <div className={accent ? "is-accent" : undefined}><strong>{value}</strong><span>{label}</span></div>
);

const EventOverviewMetric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div><span>{label}</span><strong>{value}</strong></div>
);

const EventLoadError: React.FC<{ locale: string; onRetry: () => void }> = ({ locale, onRetry }) => (
  <section className="product-container events-load-error" role="alert">
    <h2>{locale === "zh-CN" ? "赛事数据加载失败" : "Failed to load events"}</h2>
    <p>{locale === "zh-CN" ? "当前无法读取赛事，请重试。" : "Event data is unavailable right now. Try again."}</p>
    <button className="product-btn product-btn-secondary" type="button" onClick={onRetry}>{locale === "zh-CN" ? "重试" : "Retry"}</button>
  </section>
);

const StatusPill: React.FC<{ status: EventStatus; locale: string }> = ({ status, locale }) => (
  <span className={`event-v2-status status-${status.toLowerCase()}`}><i aria-hidden="true" />{statusLabel(status, locale)}</span>
);

const PhasePill: React.FC<{ phase: MapSummary["phase"]; locale: string }> = ({ phase, locale }) => {
  const { key, text } = matchPhaseBadgePresentation(phase, locale);
  return <span className={`event-series-phase is-${key}`}>{text}</span>;
};

function filterLabel(filter: EventFilter, locale: string): string {
  if (locale !== "zh-CN") return filter === "ALL" ? "All" : filter === "LIVE" ? "Live" : filter === "UPCOMING" ? "Upcoming" : "Completed";
  return filter === "ALL" ? "全部" : filter === "LIVE" ? "进行中" : filter === "UPCOMING" ? "即将开始" : "已结束";
}

function eventTabLabel(tab: EventDetailTab, locale: string): string {
  if (locale !== "zh-CN") return tab === "OVERVIEW" ? "Overview" : tab === "SCHEDULE" ? "Schedule" : tab === "UPCOMING" ? "Upcoming" : tab === "LIVE" ? "Live" : "Completed";
  return tab === "OVERVIEW" ? "总览" : tab === "SCHEDULE" ? "赛程" : tab === "UPCOMING" ? "即将开始" : tab === "LIVE" ? "进行中" : "已结束";
}

function eventScheduleTitle(tab: EventDetailTab, locale: string): string {
  if (tab === "UPCOMING") return locale === "zh-CN" ? "即将开始的比赛" : "Upcoming matches";
  if (tab === "LIVE") return locale === "zh-CN" ? "进行中的比赛" : "Live matches";
  if (tab === "COMPLETED") return locale === "zh-CN" ? "已结束的比赛" : "Completed matches";
  return locale === "zh-CN" ? "对阵与赛果" : "Matches & results";
}

function filterEventSeries(series: EventSeriesSummary[], tab: EventDetailTab): EventSeriesSummary[] {
  if (tab === "UPCOMING") return series.filter((item) => isUpcomingPhase(item.phase));
  if (tab === "LIVE") return series.filter((item) => isLivePhase(item.phase));
  if (tab === "COMPLETED") return series.filter((item) => item.phase === "POSTMATCH" || item.phase === "AWAITING_RESULT");
  return series;
}

function eventTeams(event: EventSummary): NonNullable<MapSummary["team_a"]>[] {
  const teams = new Map<string, NonNullable<MapSummary["team_a"]>>();
  for (const match of event.matches) {
    for (const team of [match.team_a, match.team_b]) {
      if (team) teams.set(team.id || team.name, team);
    }
  }
  return Array.from(teams.values());
}

function seriesFormats(series: EventSeriesSummary[]): string {
  const formats = Array.from(new Set(series.map((item) => item.bestOf).filter((value): value is number => Boolean(value))));
  return formats.length > 0 ? formats.map((value) => `BO${value}`).join(" / ") : "—";
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
