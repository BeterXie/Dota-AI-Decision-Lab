import React from "react";
import type { MapSummary } from "../api";
import { useI18n } from "../i18n";
import { formatOdds, getMatchDisplayPhase, primaryMarketPair } from "../utils/presentation";

interface PlayerMatchRailProps {
  matches: MapSummary[];
  selectedId: string | null;
  onSelectMatch: (id: string) => void;
}

export const PlayerMatchRail: React.FC<PlayerMatchRailProps> = ({ matches, selectedId, onSelectMatch }) => {
  const { locale, t } = useI18n();
  const groups = React.useMemo(() => {
    const buckets: Record<"LIVE" | "UPCOMING" | "AWAITING_RESULT" | "TRACKED" | "POSTMATCH", MapSummary[]> = {
      LIVE: [], UPCOMING: [], AWAITING_RESULT: [], TRACKED: [], POSTMATCH: []
    };
    matches.forEach((match) => buckets[getMatchDisplayPhase(match)].push(match));
    return [
      { key: "LIVE", label: locale === "zh-CN" ? "直播" : "LIVE" },
      { key: "UPCOMING", label: locale === "zh-CN" ? "即将开始" : "UPCOMING" },
      { key: "AWAITING_RESULT", label: locale === "zh-CN" ? "等待赛果" : "AWAITING RESULT" },
      { key: "TRACKED", label: locale === "zh-CN" ? "追踪中" : "TRACKED" },
      { key: "POSTMATCH", label: locale === "zh-CN" ? "已结束" : "FINISHED" }
    ].map((group) => ({ ...group, items: buckets[group.key as keyof typeof buckets] })).filter((group) => group.items.length > 0);
  }, [matches, locale]);

  return (
    <aside className="match-rail">
      <div className="match-rail-header player-rail-header">
        <h3 className="rail-title">{t("trackedMaps")}</h3>
        <span className="rail-total-count">{matches.length}</span>
      </div>
      <div className="match-rail-list player-match-groups">
        {groups.length === 0 ? <div className="empty-rail-msg">{t("noCanonicalMaps")}</div> : groups.map((group) => (
          <section className="player-match-group" key={group.key}>
            <div className="player-match-group-title">
              <span>{group.key === "LIVE" && <i className="live-group-dot" />}{group.label}</span>
              <small>{group.items.length}</small>
            </div>
            <div className="player-match-group-list">
              {group.items.map((match) => {
                const phase = getMatchDisplayPhase(match);
                const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
                const headline = phaseHeadline(phase, match.live?.game_time_seconds, match.scheduled_at, locale);
                return (
                  <button type="button" key={match.id} className={`rail-match-card player-rail-card ${match.id === selectedId ? "selected" : ""}`} onClick={() => onSelectMatch(match.id)}>
                    <div className="rail-card-top">
                      <span className={`phase-badge ${phase === "LIVE" ? "badge-live" : "badge-upcoming"}`}>{headline}</span>
                      <span className="league-info">{match.tournament_name || t("unknownTournament")}{match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}</span>
                    </div>
                    <div className="rail-card-teams">
                      <div className="team-row"><span className="team-dot team-a-order" /><span className="team-name">{match.team_a?.name ?? t("unknownTeam")}</span><span className="team-odds">{formatOdds(pair?.teamA.price)}</span></div>
                      <div className="team-row"><span className="team-dot team-b-order" /><span className="team-name">{match.team_b?.name ?? t("unknownTeam")}</span><span className="team-odds">{formatOdds(pair?.teamB.price)}</span></div>
                    </div>
                    <div className="rail-card-footer"><span className="quality-pill">{match.latest_snapshot?.mode || match.identity_status}</span><span>{phaseFooter(phase, locale)}</span></div>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
};

function phaseHeadline(phase: ReturnType<typeof getMatchDisplayPhase>, gameTime: number | null | undefined, scheduledAt: string | null, locale: string): string {
  if (phase === "LIVE" && gameTime != null) return `● ${formatGameTime(gameTime)}`;
  if (phase === "AWAITING_RESULT") return locale === "zh-CN" ? "等待赛果" : "AWAITING";
  if (phase === "POSTMATCH") return locale === "zh-CN" ? "已结束" : "FINISHED";
  return scheduleLabel(scheduledAt, locale);
}

function phaseFooter(phase: ReturnType<typeof getMatchDisplayPhase>, locale: string): string {
  const zh = locale === "zh-CN";
  if (phase === "LIVE") return zh ? "进行中" : "IN PLAY";
  if (phase === "UPCOMING") return zh ? "赛前" : "PREMATCH";
  if (phase === "AWAITING_RESULT") return zh ? "结算待确认" : "RESULT PENDING";
  if (phase === "POSTMATCH") return zh ? "赛后" : "POSTMATCH";
  return zh ? "状态确认中" : "STATUS PENDING";
}

function formatGameTime(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function scheduleLabel(value: string | null, locale: string): string {
  if (!value) return locale === "zh-CN" ? "待定" : "TBD";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return locale === "zh-CN" ? "待定" : "TBD";
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}
