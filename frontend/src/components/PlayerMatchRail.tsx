import React from "react";
import type { MapSummary } from "../api";
import { useI18n } from "../i18n";
import { formatOdds, getMatchDisplayPhase, primaryMarketPair } from "../utils/presentation";
import { getTeamLogoUrl, getTeamAbbreviation } from "../utils/dotaAssets";

interface PlayerMatchRailProps {
  matches: MapSummary[];
  selectedId: string | null;
  onSelectMatch: (id: string) => void;
}

const teamADotStyle: React.CSSProperties = { background: "#7C9CFF", boxShadow: "0 0 8px rgba(124,156,255,.35)" };
const teamBDotStyle: React.CSSProperties = { background: "#9C82FF", boxShadow: "0 0 8px rgba(156,130,255,.35)" };

function parseMatchTimestamp(m: MapSummary): number {
  const t = m.scheduled_at || m.provider_observed_at || m.live?.received_at || "";
  const d = Date.parse(t);
  return Number.isNaN(d) ? 0 : d;
}

function getMatchDecisionBadge(match: MapSummary): { text: string; kind: "buy-a" | "buy-b" | "hold" | "nobuy" } | null {
  if (!match.decisions || match.decisions.length === 0) return null;
  const buys = match.decisions.filter(
    (d) => d.decision?.action === "BUY_A" || d.decision?.action === "BUY_B"
  );
  if (buys.length > 0) {
    const best = buys[0];
    const prob = best.decision?.fair_probability_a ? Math.round(best.decision.fair_probability_a * 100) : null;
    const label = best.decision?.action === "BUY_A" ? "BUY A" : "BUY B";
    return {
      text: prob ? `${label} ${prob}%` : label,
      kind: best.decision?.action === "BUY_A" ? "buy-a" : "buy-b"
    };
  }
  const anyDecision = match.decisions.find((d) => d.decision?.action);
  if (anyDecision?.decision?.action) {
    const act = anyDecision.decision.action;
    if (act === "HOLD") return { text: "HOLD", kind: "hold" };
    if (act === "NO_BUY") return { text: "NO BUY", kind: "nobuy" };
  }
  return null;
}

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

    // Sort within buckets by date/time
    // Finished matches: reverse chronological (newest finished first)
    buckets.POSTMATCH.sort((a, b) => parseMatchTimestamp(b) - parseMatchTimestamp(a));

    // Upcoming matches: chronological (earliest starting first)
    buckets.UPCOMING.sort((a, b) => parseMatchTimestamp(a) - parseMatchTimestamp(b));

    // Live matches: prioritize BUY decisions first, then active game time
    buckets.LIVE.sort((a, b) => {
      const aBuy = a.decisions?.some((d) => d.decision?.action === "BUY_A" || d.decision?.action === "BUY_B") ? 1 : 0;
      const bBuy = b.decisions?.some((d) => d.decision?.action === "BUY_A" || d.decision?.action === "BUY_B") ? 1 : 0;
      if (aBuy !== bBuy) return bBuy - aBuy;
      return (b.live?.game_time_seconds || 0) - (a.live?.game_time_seconds || 0);
    });

    buckets.AWAITING_RESULT.sort((a, b) => parseMatchTimestamp(b) - parseMatchTimestamp(a));
    buckets.TRACKED.sort((a, b) => parseMatchTimestamp(b) - parseMatchTimestamp(a));

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

  const scrollToGroup = (key: string) => {
    const node = groupRefs.current[key];
    if (node && listRef.current) {
      listRef.current.scrollTo({ left: node.offsetLeft - 14, behavior: "smooth" });
      setActiveGroup(key);
    }
  };

  const scrollByPage = (direction: -1 | 1) => {
    const el = listRef.current;
    if (!el) return;
    el.scrollBy({ left: direction * Math.max(260, el.clientWidth * 0.75), behavior: "smooth" });
  };

  return (
    <aside className="match-rail">
      <div className="match-rail-header player-rail-header">
        <div className="rail-title-row">
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
                const headline = phaseHeadline(phase, match.live?.game_time_seconds, match.scheduled_at || match.provider_observed_at, locale);
                const aiBadge = getMatchDecisionBadge(match);
                const teamA = match.team_a?.name ?? t("unknownTeam");
                const teamB = match.team_b?.name ?? t("unknownTeam");
                const teamALogo = getTeamLogoUrl(teamA);
                const teamBLogo = getTeamLogoUrl(teamB);

                return (
                  <button type="button" key={match.id} data-match-id={match.id} className={`rail-match-card player-rail-card ${match.id === selectedId ? "selected" : ""}`} onClick={() => handleSelect(match.id)}>
                    <div className="rail-card-top">
                      <span className={`phase-badge ${phase === "LIVE" ? "badge-live" : "badge-upcoming"}`}>{headline}</span>
                      <span className="league-info">{match.tournament_name || t("unknownTournament")}{match.map_number ? ` · ${t("map")} ${match.map_number}` : ""}</span>
                    </div>
                    <div className="rail-card-teams">
                      <div className="team-row">
                        {teamALogo ? (
                          <img src={teamALogo} alt={teamA} className="rail-team-mini-logo" onError={(e) => { (e.currentTarget as HTMLElement).style.display = "none"; }} />
                        ) : (
                          <span className="team-dot team-a-order" style={teamADotStyle} />
                        )}
                        <span className="team-name">{teamA}</span>
                        <span className="team-odds">{formatOdds(pair?.teamA.price)}</span>
                      </div>
                      <div className="team-row">
                        {teamBLogo ? (
                          <img src={teamBLogo} alt={teamB} className="rail-team-mini-logo" onError={(e) => { (e.currentTarget as HTMLElement).style.display = "none"; }} />
                        ) : (
                          <span className="team-dot team-b-order" style={teamBDotStyle} />
                        )}
                        <span className="team-name">{teamB}</span>
                        <span className="team-odds">{formatOdds(pair?.teamB.price)}</span>
                      </div>
                    </div>
                    <div className="rail-card-footer">
                      {aiBadge ? (
                        <span className={`rail-ai-badge ${aiBadge.kind}`}>{aiBadge.text}</span>
                      ) : (
                        <span className="quality-pill">{match.latest_snapshot?.mode || match.identity_status}</span>
                      )}
                      <span>{phaseFooter(phase, locale)}</span>
                    </div>
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
  if (phase === "POSTMATCH") return scheduleDateLabel(scheduledAt, locale) || (locale === "zh-CN" ? "已结束" : "FINISHED");
  return scheduleDateLabel(scheduledAt, locale) || (locale === "zh-CN" ? "即将开赛" : "UPCOMING");
}

function phaseFooter(phase: ReturnType<typeof getMatchDisplayPhase>, locale: string): string {
  const zh = locale === "zh-CN";
  if (phase === "LIVE") return zh ? "进行中" : "IN PLAY";
  if (phase === "UPCOMING") return zh ? "赛前" : "PREMATCH";
  if (phase === "AWAITING_RESULT") return zh ? "赛果待确认" : "RESULT PENDING";
  if (phase === "POSTMATCH") return zh ? "已结束" : "POSTMATCH";
  return zh ? "状态确认中" : "STATUS PENDING";
}

function formatGameTime(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function scheduleDateLabel(value: string | null | undefined, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return null;
  try {
    return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
      timeZone: "Asia/Shanghai",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(date);
  } catch {
    return new Intl.DateTimeFormat(locale, {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date);
  }
}
