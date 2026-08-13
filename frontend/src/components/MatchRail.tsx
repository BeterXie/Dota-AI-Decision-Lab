import React from "react";
import type { MapSummary } from "../api";
import { translateStatus, useI18n } from "../i18n";

export type MatchCategory = "ALL" | "LIVE" | "PREMATCH" | "POSTMATCH";

interface MatchRailProps {
  matches: MapSummary[];
  selectedId: string | null;
  category: MatchCategory;
  onSelectCategory: (cat: MatchCategory) => void;
  onSelectMatch: (id: string) => void;
}

export const MatchRail: React.FC<MatchRailProps> = ({
  matches,
  selectedId,
  category,
  onSelectCategory,
  onSelectMatch
}) => {
  const { locale, t } = useI18n();
  const counts = React.useMemo(() => {
    let live = 0;
    let prematch = 0;
    let postmatch = 0;
    matches.forEach((m) => {
      const p = m.phase ?? "UNKNOWN";
      if (p === "LIVE") live++;
      else if (p === "PREMATCH") prematch++;
      else if (p === "POSTMATCH" || p === "AWAITING_RESULT") postmatch++;
    });
    return { all: matches.length, live, prematch, postmatch };
  }, [matches]);

  const filteredMatches = React.useMemo(() => {
    if (category === "ALL") return matches;
    if (category === "LIVE") return matches.filter((m) => m.phase === "LIVE");
    if (category === "PREMATCH") return matches.filter((m) => m.phase === "PREMATCH");
    return matches.filter((m) => m.phase === "POSTMATCH" || m.phase === "AWAITING_RESULT");
  }, [matches, category]);

  return (
    <aside className="match-rail">
      <div className="match-rail-header">
        <h3 className="rail-title">{t("trackedMaps")}</h3>
        <div className="rail-tabs">
          <button
            className={`rail-tab ${category === "LIVE" ? "active" : ""}`}
            onClick={() => onSelectCategory("LIVE")}
          >
            {t("liveCategory")} <span className="tab-count">{counts.live}</span>
          </button>
          <button
            className={`rail-tab ${category === "PREMATCH" ? "active" : ""}`}
            onClick={() => onSelectCategory("PREMATCH")}
          >
            {t("prematchCategory")} <span className="tab-count">{counts.prematch}</span>
          </button>
          <button
            className={`rail-tab ${category === "POSTMATCH" ? "active" : ""}`}
            onClick={() => onSelectCategory("POSTMATCH")}
          >
            {t("postmatchCategory")} <span className="tab-count">{counts.postmatch}</span>
          </button>
        </div>
      </div>

      <div className="match-rail-list">
        {filteredMatches.length === 0 ? (
          <div className="empty-rail-msg">{t("noCanonicalMaps")}</div>
        ) : (
          filteredMatches.map((match) => {
            const isSelected = match.id === selectedId;
            const isLive = match.phase === "LIVE";
            const teamA = match.team_a?.name ?? t("unknownTeam");
            const teamB = match.team_b?.name ?? t("unknownTeam");
            const oddsA = match.market?.[0]?.price ? Number(match.market[0].price).toFixed(2) : "—";
            const oddsB = match.market?.[1]?.price ? Number(match.market[1].price).toFixed(2) : "—";
            const gameTimeStr = isLive && match.live?.game_time_seconds
              ? `${Math.floor(match.live.game_time_seconds / 60)}:${String(
                  match.live.game_time_seconds % 60
                ).padStart(2, "0")}`
              : null;

            const dataQuality = match.latest_snapshot?.mode;

            return (
              <div
                key={match.id}
                className={`rail-match-card ${isSelected ? "selected" : ""}`}
                onClick={() => onSelectMatch(match.id)}
              >
                <div className="rail-card-top">
                  <span className={`phase-badge ${isLive ? "badge-live" : "badge-upcoming"}`}>
                    {isLive && gameTimeStr
                      ? `● ${translateStatus("LIVE", locale)} · ${gameTimeStr}`
                      : translateStatus(match.phase, locale)}
                  </span>
                  <span className="league-info">
                    {match.tournament_name || t("unknownTournament")}
                    {match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}
                  </span>
                </div>

                <div className="rail-card-teams">
                  <div className="team-row">
                    <span className="team-name">{teamA}</span>
                    <span className="team-odds">{oddsA}</span>
                  </div>
                  <div className="team-row">
                    <span className="team-name">{teamB}</span>
                    <span className="team-odds">{oddsB}</span>
                  </div>
                </div>

                <div className="rail-card-footer">
                  <span className="quality-pill">
                    {dataQuality ? translateStatus(dataQuality, locale) : t("noSnapshot")}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
};
