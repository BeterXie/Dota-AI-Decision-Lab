import React from "react";
import type { MapSummary } from "../api";
import { useI18n } from "../i18n";
import { formatOdds, getMatchDisplayPhase, primaryMarketPair } from "../utils/presentation";

interface PlayerMatchRailProps {
  matches: MapSummary[];
  selectedId: string | null;
  onSelectMatch: (id: string) => void;
}

const teamADotStyle: React.CSSProperties = { background: "#7C9CFF", boxShadow: "0 0 8px rgba(124,156,255,.35)" };
const teamBDotStyle: React.CSSProperties = { background: "#9C82FF", boxShadow: "0 0 8px rgba(156,130,255,.35)" };

export const PlayerMatchRail: React.FC<PlayerMatchRailProps> = ({ matches, selectedId, onSelectMatch }) => {
  const { locale, t } = useI18n();
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const groupRefs = React.useRef<Record<string, HTMLElement | null>>({});
  const lastClickedRef = React.useRef<string | null>(null);
  const [canScrollLeft, setCanScrollLeft] = React.useState(false);
  const [canScrollRight, setCanScrollRight] = React.useState(false);
  const [activeGroup, setActiveGroup] = React.useState<string | null>(null);

  const groups = React.useMemo(() => {
    const buckets: Record<"LIVE" | "UPCOMING" | "AWAITING_RESULT" | "TRACKED" | "POSTMATCH", MapSummary[]> = {
      LIVE: [], UPCOMING: [], AWAITING_RESULT: [], TRACKED: [], POSTMATCH: []
    };
    matches.forEach((match) => buckets[getMatchDisplayPhase(match)].push(match));
    return [
      { key: "LIVE", label: locale === "zh-CN" ? "直播" : "LIVE", chipLabel: locale === "zh-CN" ? "直播" : "LIVE" },
      { key: "UPCOMING", label: locale === "zh-CN" ? "即将开始" : "UPCOMING", chipLabel: locale === "zh-CN" ? "即将开始" : "UPCOMING" },
      { key: "AWAITING_RESULT", label: locale === "zh-CN" ? "等待赛果" : "AWAITING RESULT", chipLabel: locale === "zh-CN" ? "等待赛果" : "AWAITING" },
      { key: "TRACKED", label: locale === "zh-CN" ? "追踪中" : "TRACKED", chipLabel: locale === "zh-CN" ? "追踪中" : "TRACKED" },
      { key: "POSTMATCH", label: locale === "zh-CN" ? "已结束" : "FINISHED", chipLabel: locale === "zh-CN" ? "已结束" : "FINISHED" }
    ].map((group) => ({ ...group, items: buckets[group.key as keyof typeof buckets] })).filter((group) => group.items.length > 0);
  }, [matches, locale]);
  const groupsRef = React.useRef(groups);
  groupsRef.current = groups;

  // While the pointer hovers the rail, vertical wheel scrolls horizontally.
  // This removes the "drag the scrollbar" step for mouse users; shift+wheel
  // still works natively.
  React.useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      event.preventDefault();
      el.scrollLeft += event.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const refreshScrollState = React.useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
    const center = el.scrollLeft + el.clientWidth / 2;
    let current: string | null = null;
    for (const group of groupsRef.current) {
      const node = groupRefs.current[group.key];
      if (node && node.offsetLeft <= center && node.offsetLeft + node.offsetWidth >= center) {
        current = group.key;
        break;
      }
    }
    if (current === null && groupsRef.current.length > 0) current = groupsRef.current[0].key;
    setActiveGroup(current);
  }, []);

  React.useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    refreshScrollState();
    el.addEventListener("scroll", refreshScrollState, { passive: true });
    window.addEventListener("resize", refreshScrollState);
    return () => {
      el.removeEventListener("scroll", refreshScrollState);
      window.removeEventListener("resize", refreshScrollState);
    };
  }, [refreshScrollState]);

  // Programmatic selection changes (e.g. the tracked match rotated out and the
  // app fell back to the first match) keep the selected card visible.  Manual
  // clicks skip the scroll because the card is already under the pointer.
  React.useEffect(() => {
    if (selectedId == null || selectedId === lastClickedRef.current) return;
    const card = listRef.current?.querySelector<HTMLElement>(`[data-match-id="${selectedId}"]`);
    if (card && typeof card.scrollIntoView === "function") {
      card.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    }
  }, [selectedId]);

  const handleSelect = (id: string) => {
    lastClickedRef.current = id;
    onSelectMatch(id);
  };

  const scrollByPage = (direction: 1 | -1) => {
    const el = listRef.current;
    if (!el || typeof el.scrollBy !== "function") return;
    el.scrollBy({ left: direction * el.clientWidth * 0.85, behavior: "smooth" });
  };

  const scrollToGroup = (key: string) => {
    const el = listRef.current;
    const node = groupRefs.current[key];
    if (!el || !node || typeof el.scrollTo !== "function") return;
    el.scrollTo({ left: Math.max(0, node.offsetLeft - 12), behavior: "smooth" });
  };

  return (
    <aside className="match-rail">
      <div className="match-rail-header player-rail-header">
        <div className="rail-header-top">
          <h3 className="rail-title">{t("trackedMaps")}</h3>
          <span className="rail-total-count">{matches.length}</span>
        </div>
        {groups.length > 0 && (
          <nav className="rail-group-chips" aria-label={locale === "zh-CN" ? "比赛分组" : "Match groups"}>
            {groups.map((group) => (
              <button key={group.key} type="button" className={`rail-group-chip ${group.key === activeGroup ? "active" : ""}`} onClick={() => scrollToGroup(group.key)}>
                {group.key === "LIVE" && <i className="live-group-dot" />}{group.chipLabel}<b>{group.items.length}</b>
              </button>
            ))}
          </nav>
        )}
      </div>
      <div className="match-rail-list player-match-groups" ref={listRef}>
        {groups.length === 0 ? <div className="empty-rail-msg">{t("noCanonicalMaps")}</div> : groups.map((group) => (
          <section className="player-match-group" key={group.key} ref={(node) => { groupRefs.current[group.key] = node; }}>
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
                  <button type="button" key={match.id} data-match-id={match.id} className={`rail-match-card player-rail-card ${match.id === selectedId ? "selected" : ""}`} onClick={() => handleSelect(match.id)}>
                    <div className="rail-card-top">
                      <span className={`phase-badge ${phase === "LIVE" ? "badge-live" : "badge-upcoming"}`}>{headline}</span>
                      <span className="league-info">{match.tournament_name || t("unknownTournament")}{match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}</span>
                    </div>
                    <div className="rail-card-teams">
                      <div className="team-row"><span className="team-dot team-a-order" style={teamADotStyle} /><span className="team-name">{match.team_a?.name ?? t("unknownTeam")}</span><span className="team-odds">{formatOdds(pair?.teamA.price)}</span></div>
                      <div className="team-row"><span className="team-dot team-b-order" style={teamBDotStyle} /><span className="team-name">{match.team_b?.name ?? t("unknownTeam")}</span><span className="team-odds">{formatOdds(pair?.teamB.price)}</span></div>
                    </div>
                    <div className="rail-card-footer"><span className="quality-pill">{match.latest_snapshot?.mode || match.identity_status}</span><span>{phaseFooter(phase, locale)}</span></div>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>
      {canScrollLeft && <button type="button" className="rail-scroll-arrow rail-arrow-left" onClick={() => scrollByPage(-1)} aria-label={locale === "zh-CN" ? "向左滚动比赛列表" : "Scroll match list left"}>‹</button>}
      {canScrollRight && <button type="button" className="rail-scroll-arrow rail-arrow-right" onClick={() => scrollByPage(1)} aria-label={locale === "zh-CN" ? "向右滚动比赛列表" : "Scroll match list right"}>›</button>}
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
  if (phase === "AWAITING_RESULT") return zh ? "赛果待确认" : "RESULT PENDING";
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
