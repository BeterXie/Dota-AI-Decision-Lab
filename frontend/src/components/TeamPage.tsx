import React from "react";
import { useQuery } from "@tanstack/react-query";

import type { MapSummary } from "../api";
import { eventHref, eventName } from "../events";
import { useI18n } from "../i18n";
import { isLivePhase, isUpcomingPhase } from "../matchPhase";
import { matchHref } from "../matches";
import {
  fetchTeamDetail,
  type TeamDetail,
  type TeamRosterMembership
} from "../teamDirectoryApi";
import { TeamCrest, UiIcon } from "./VisualIdentity";

interface TeamPageProps {
  slug: string;
  matches: MapSummary[];
  matchesLoading: boolean;
}

export const TeamPage: React.FC<TeamPageProps> = ({ slug, matches, matchesLoading }) => {
  const { locale } = useI18n();
  const team = useQuery({
    queryKey: ["product", "team", slug],
    queryFn: () => fetchTeamDetail(slug),
    staleTime: 5 * 60_000,
    retry: 1
  });

  if (team.isLoading) return <TeamPageSkeleton />;
  if (team.isError || !team.data) return <TeamNotFound locale={locale} />;

  const detail = team.data;
  const currentPlayers = detail.current_roster
    .filter((item) => item.role === "PLAYER" && item.subject.type === "PLAYER")
    .sort((a, b) => (a.position ?? 99) - (b.position ?? 99));
  const currentStaff = detail.current_roster.filter(
    (item) => item.role !== "PLAYER" && item.subject.type === "STAFF"
  );
  const teamMatches = matches.filter((match) => matchHasTeam(match, detail.id));
  const upcoming = teamMatches
    .filter((match) => isLivePhase(match.phase) || isUpcomingPhase(match.phase))
    .sort(byScheduledAscending)
    .slice(0, 5);
  const recent = teamMatches
    .filter((match) => match.phase === "POSTMATCH" || match.phase === "AWAITING_RESULT")
    .sort(byScheduledDescending)
    .slice(0, 5);
  const history = detail.roster_history
    .filter((item) => item.valid_to !== null)
    .sort((a, b) => dateValue(b.valid_to) - dateValue(a.valid_to))
    .slice(0, 10);

  return (
    <div className="team-v2">
      <section className="product-container team-crumbs">
        <a href="/events">{locale === "zh-CN" ? "赛事" : "Events"}</a>
        <span>›</span>
        <strong>{detail.name}</strong>
      </section>

      <section className="product-container team-hero-v2">
        <div className="team-hero-logo">
          <TeamCrest
            team={{ id: detail.id, name: detail.name }}
            fallbackName={detail.name}
            size="lg"
            link={false}
          />
        </div>
        <div className="team-hero-copy">
          <span className="home-eyebrow">TEAM PROFILE</span>
          <div className="team-title-line">
            <h1>{detail.name}</h1>
            {detail.short_name ? <b>{detail.short_name}</b> : null}
          </div>
          <p>
            {locale === "zh-CN"
              ? "公开战队资料、当前阵容与可追溯的成员变动。阵容数据只展示已记录来源，不补写未知信息。"
              : "Public team identity, current roster and traceable membership history. Unknown roster details are not invented."}
          </p>
          <div className="team-meta-row">
            {detail.country_code ? <span>{detail.country_code}</span> : null}
            {detail.valve_team_id ? <span>Dota Team ID {detail.valve_team_id}</span> : null}
            <span>{locale === "zh-CN" ? `${currentPlayers.length} 名当前选手` : `${currentPlayers.length} current players`}</span>
          </div>
        </div>
        <div className="team-hero-actions">
          {detail.website_url ? (
            <a className="product-btn product-btn-secondary" href={detail.website_url} target="_blank" rel="noreferrer">
              {locale === "zh-CN" ? "战队官网" : "Team website"}
            </a>
          ) : null}
          {detail.source_url ? (
            <a className="team-source-link" href={detail.source_url} target="_blank" rel="noreferrer">
              {locale === "zh-CN" ? "查看资料来源" : "View source"}<span>↗</span>
            </a>
          ) : null}
        </div>
      </section>

      <div className="product-container team-main-grid product-section">
        <section className="team-roster-panel">
          <PanelTitle
            eyebrow="ROSTER"
            title={locale === "zh-CN" ? "当前阵容" : "Current roster"}
            aside={detail.observed_at ? formatObserved(detail.observed_at, locale) : undefined}
          />
          {currentPlayers.length > 0 ? (
            <div className="team-player-grid">
              {currentPlayers.map((membership) => (
                <PlayerCard key={membership.id} membership={membership} locale={locale} />
              ))}
            </div>
          ) : (
            <EmptyTeamState
              text={locale === "zh-CN" ? "当前阵容还没有可靠记录。" : "No reliable current roster is recorded yet."}
            />
          )}

          <div className="team-staff-block">
            <h3>{locale === "zh-CN" ? "教练与工作人员" : "Coaches & staff"}</h3>
            {currentStaff.length > 0 ? (
              <div className="team-staff-list">
                {currentStaff.map((membership) => (
                  <StaffRow key={membership.id} membership={membership} locale={locale} />
                ))}
              </div>
            ) : (
              <p>{locale === "zh-CN" ? "暂无已确认的教练或工作人员资料。" : "No confirmed coach or staff record yet."}</p>
            )}
          </div>
        </section>

        <aside className="team-side-column">
          <section className="team-match-panel">
            <PanelTitle eyebrow="SCHEDULE" title={locale === "zh-CN" ? "正在参加 / 即将比赛" : "Live & upcoming"} />
            {matchesLoading ? (
              <TeamMatchSkeleton />
            ) : upcoming.length > 0 ? (
              <div className="team-match-list">
                {upcoming.map((match) => <TeamMatchRow key={match.id} match={match} locale={locale} />)}
              </div>
            ) : (
              <EmptyTeamState text={locale === "zh-CN" ? "目前没有已同步的近期赛程。" : "No upcoming synced matches."} />
            )}
          </section>

          <section className="team-match-panel">
            <PanelTitle eyebrow="RESULTS" title={locale === "zh-CN" ? "最近比赛" : "Recent matches"} />
            {matchesLoading ? (
              <TeamMatchSkeleton />
            ) : recent.length > 0 ? (
              <div className="team-match-list">
                {recent.map((match) => <TeamMatchRow key={match.id} match={match} locale={locale} />)}
              </div>
            ) : (
              <EmptyTeamState text={locale === "zh-CN" ? "目前没有已同步的近期赛果。" : "No recent synced results."} />
            )}
          </section>
        </aside>
      </div>

      <section className="product-container team-history-panel product-section">
        <PanelTitle
          eyebrow="HISTORY"
          title={locale === "zh-CN" ? "阵容变动记录" : "Roster history"}
          aside={locale === "zh-CN" ? "按离队时间倒序" : "Newest departures first"}
        />
        {history.length > 0 ? (
          <div className="team-history-list">
            {history.map((membership) => (
              <HistoryRow key={membership.id} membership={membership} locale={locale} />
            ))}
          </div>
        ) : (
          <EmptyTeamState text={locale === "zh-CN" ? "还没有历史阵容变动记录。" : "No roster changes have been recorded yet."} />
        )}
      </section>
    </div>
  );
};

const PlayerCard: React.FC<{ membership: TeamRosterMembership; locale: string }> = ({ membership, locale }) => {
  const subject = membership.subject;
  return (
    <article className="team-player-card">
      <div className="team-player-avatar" aria-hidden="true">
        {subject.avatar_url ? <img src={subject.avatar_url} alt="" loading="lazy" /> : <span>{initials(subject.name || subject.real_name)}</span>}
      </div>
      <div>
        <span>{membership.position ? positionLabel(membership.position, locale) : (locale === "zh-CN" ? "选手" : "Player")}</span>
        <h3>{subject.name || subject.real_name || (locale === "zh-CN" ? "未知选手" : "Unknown player")}</h3>
        <p>{subject.real_name && subject.real_name !== subject.name ? subject.real_name : subject.country_code || "—"}</p>
      </div>
      {membership.is_standin ? <b className="team-roster-badge">STAND-IN</b> : null}
    </article>
  );
};

const StaffRow: React.FC<{ membership: TeamRosterMembership; locale: string }> = ({ membership, locale }) => (
  <div className="team-staff-row">
    <span>{roleLabel(membership.role, locale)}</span>
    <strong>{membership.subject.name || membership.subject.real_name || "—"}</strong>
    <small>{membership.subject.real_name && membership.subject.real_name !== membership.subject.name ? membership.subject.real_name : membership.subject.country_code || "—"}</small>
  </div>
);

const HistoryRow: React.FC<{ membership: TeamRosterMembership; locale: string }> = ({ membership, locale }) => (
  <div className="team-history-row">
    <div>
      <strong>{membership.subject.name || membership.subject.real_name || "—"}</strong>
      <span>{membership.role === "PLAYER" && membership.position ? positionLabel(membership.position, locale) : roleLabel(membership.role, locale)}</span>
    </div>
    <p>{formatMembershipRange(membership, locale)}</p>
    <small>{membership.source_name}</small>
  </div>
);

const TeamMatchRow: React.FC<{ match: MapSummary; locale: string }> = ({ match, locale }) => {
  const event = eventName(match);
  const a = match.team_a?.name || (locale === "zh-CN" ? "待定" : "TBD");
  const b = match.team_b?.name || (locale === "zh-CN" ? "待定" : "TBD");
  return (
    <article className="team-match-row">
      <div className="team-match-event">
        <a href={eventHref(event)}>{event}</a>
        <time>{match.scheduled_at ? formatDateTime(match.scheduled_at, locale) : "—"}</time>
      </div>
      <div className="team-match-pair">
        <span><TeamCrest team={match.team_a} fallbackName={a} size="sm" />{a}</span>
        <b>{scoreText(match)}</b>
        <span><TeamCrest team={match.team_b} fallbackName={b} size="sm" />{b}</span>
      </div>
      <a className="team-match-open" href={matchHref(match)}>{locale === "zh-CN" ? "比赛详情" : "Match details"}<span>›</span></a>
    </article>
  );
};

const PanelTitle: React.FC<{ eyebrow: string; title: string; aside?: string }> = ({ eyebrow, title, aside }) => (
  <div className="team-panel-title">
    <div><span className="home-eyebrow">{eyebrow}</span><h2>{title}</h2></div>
    {aside ? <small>{aside}</small> : null}
  </div>
);

const TeamPageSkeleton = () => (
  <div className="team-v2 product-container team-page-skeleton">
    <div className="team-skeleton-hero" />
    <div className="team-skeleton-grid"><div /><div /></div>
  </div>
);

const TeamMatchSkeleton = () => <div className="team-match-skeleton"><i /><i /><i /></div>;

const TeamNotFound: React.FC<{ locale: string }> = ({ locale }) => (
  <section className="product-container team-not-found">
    <span aria-hidden="true">◇</span>
    <h1>{locale === "zh-CN" ? "没有找到这支战队" : "Team not found"}</h1>
    <p>{locale === "zh-CN" ? "战队资料可能还没有完成身份同步。" : "The team identity may not have been populated yet."}</p>
    <a className="product-btn product-btn-primary" href="/events">{locale === "zh-CN" ? "返回赛事" : "Back to events"}</a>
  </section>
);

const EmptyTeamState: React.FC<{ text: string }> = ({ text }) => <div className="team-empty-state"><span aria-hidden="true">◇</span><p>{text}</p></div>;

function matchHasTeam(match: MapSummary, teamId: string): boolean {
  return match.team_a?.id === teamId || match.team_b?.id === teamId;
}

function byScheduledAscending(a: MapSummary, b: MapSummary): number {
  return dateValue(a.scheduled_at) - dateValue(b.scheduled_at);
}

function byScheduledDescending(a: MapSummary, b: MapSummary): number {
  return dateValue(b.scheduled_at) - dateValue(a.scheduled_at);
}

function dateValue(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function scoreText(match: MapSummary): string {
  if (match.series_score && (isLivePhase(match.phase) || match.phase === "POSTMATCH" || match.phase === "AWAITING_RESULT")) {
    return `${match.series_score.team_a} : ${match.series_score.team_b}`;
  }
  return "VS";
}

function positionLabel(position: number, locale: string): string {
  if (locale === "zh-CN") return `${position} 号位`;
  return `Position ${position}`;
}

function roleLabel(role: string, locale: string): string {
  if (locale !== "zh-CN") return role.replaceAll("_", " ").toLowerCase();
  const labels: Record<string, string> = {
    COACH: "教练",
    ASSISTANT_COACH: "助理教练",
    ANALYST: "分析师",
    MANAGER: "经理",
    PLAYER: "选手"
  };
  return labels[role] || role;
}

function formatMembershipRange(membership: TeamRosterMembership, locale: string): string {
  const start = membership.valid_from ? formatDate(membership.valid_from, locale) : (locale === "zh-CN" ? "加入时间未知" : "Start unknown");
  const end = membership.valid_to ? formatDate(membership.valid_to, locale) : (locale === "zh-CN" ? "至今" : "present");
  return `${start} — ${end}`;
}

function formatObserved(value: string, locale: string): string {
  return locale === "zh-CN" ? `资料更新 ${formatDate(value, locale)}` : `Updated ${formatDate(value, locale)}`;
}

function formatDate(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric"
  }).format(new Date(value));
}

function formatDateTime(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value));
}

function initials(value: string | null): string {
  if (!value) return "?";
  return value.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
}
