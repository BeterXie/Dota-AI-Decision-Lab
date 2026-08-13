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
    const live: MapSummary[] = [];
    const upcoming: MapSummary[] = [];
    const tracked: MapSummary[] = [];
    matches.forEach((match) => {
      const phase = getMatchDisplayPhase(match);
      if (phase === "LIVE") live.push(match);
      else if (phase === "UPCOMING") upcoming.push(match);
      else tracked.push(match);
    });
    return [
      { key: "live", label: locale === "zh-CN" ? "直播" : "LIVE", items: live },
      { key: "upcoming", label: locale === "zh-CN" ? "即将开始" : "UPCOMING", items: upcoming },
      { key: "tracked", label: locale === "zh-CN" ? "追踪中" : "TRACKED", items: tracked }
    ].filter((group) => group.items.length > 0);
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
              <span>{group.key === "live" && <i className="live-group-dot" />}{group.label}</span>
              <small>{group.items.length}</small>
            </div>
            <div className="player-match-group-list">
              {group.items.map((match) => {
                const phase = getMatchDisplayPhase(match);
                const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
                const gameTime = match.live?.game_time_seconds;
                const timeLabel = phase === "LIVE" && gameTime != null
                  ? `${Math.floor(gameTime / 60)}:${String(Math.max(0, gameTime % 60)).padStart(2, "0")}`
                  : scheduleLabel(match.scheduled_at, locale);
                return (
                  <button type="button" key={match.id} className={`rail-match-card player-rail-card ${match.id === selectedId ? "selected" : ""}`} onClick={() => onSelectMatch(match.id)}>
                    <div className="rail-card-top">
                      <span className={`phase-badge ${phase === "LIVE" ? "badge-live" : "badge-upcoming"}`}>{phase === "LIVE" ? `● ${timeLabel}` : timeLabel}</span>
                      <span className="league-info">{match.tournament_name || t("unknownTournament")}{match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}</span>
                    </div>
                    <div className="rail-card-teams">
                      <div className="team-row"><span className="team-dot radiant" /><span className="team-name">{match.team_a?.name ?? t("unknownTeam")}</span><span className="team-odds">{formatOdds(pair?.teamA.price)}</span></div>
                      <div className="team-row"><span className="team-dot dire" /><span className="team-name">{match.team_b?.name ?? t("unknownTeam")}</span><span className="team-odds">{formatOdds(pair?.teamB.price)}</span></div>
                    </div>
                    <div className="rail-card-footer"><span className="quality-pill">{match.latest_snapshot?.mode || match.identity_status}</span></div>
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

function scheduleLabel(value: string | null, locale: string): string {
  if (!value) return locale === "zh-CN" ? "待定" : "TBD";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return locale === "zh-CN" ? "待定" : "TBD";
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}
