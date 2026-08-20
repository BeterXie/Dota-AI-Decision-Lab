import React, { useEffect, useState } from "react";
import type { MapDetail, MapSummary } from "../api";
import { fetchDraftHeroRecent, type HeroRecentUseSummary } from "../heroRecentApi";
import { getHeroPortraitUrl, getPositionLabel, getPositionRole } from "../utils/dotaAssets";
import { resolveVerifiedMapSides } from "../utils/mapSides";
import { useI18n } from "../i18n";

interface LineupCardProps {
  match: MapSummary | MapDetail;
}

type HeroRecentLoadState = "idle" | "loading" | "ready" | "error";

interface HeroSlotData {
  side: "radiant" | "dire";
  position: number;
  playerName: string;
  heroName: string;
  heroPicked: boolean;
  playerResolved: boolean;
  heroRecent: HeroRecentUseSummary | null;
  heroRecentState: HeroRecentLoadState;
}

export const LineupCard: React.FC<LineupCardProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const [selectedSlot, setSelectedSlot] = useState<HeroSlotData | null>(null);
  const [heroRecent, setHeroRecent] = useState<Awaited<ReturnType<typeof fetchDraftHeroRecent>> | null>(null);
  const [heroRecentState, setHeroRecentState] = useState<HeroRecentLoadState>("idle");
  const apiSlots = match.draft?.slots;
  const sides = resolveVerifiedMapSides(match);
  // Refetch when the latest draft actually changes: a live match can mount
  // while heroes are still unknown and the draft completes moments later.
  const draftRevision = React.useMemo(() => {
    const observedAt = match.draft?.observed_at ?? "";
    const slotIdentity = (apiSlots ?? [])
      .map((slot) => `${slot.canonical_player_id}:${slot.hero_id}:${slot.position}`)
      .join("|");
    return `${observedAt}|${slotIdentity}`;
  }, [apiSlots, match.draft?.observed_at]);

  useEffect(() => {
    const canonicalMapId = match.canonical_map_id;
    if (!canonicalMapId) {
      setHeroRecent(null);
      setHeroRecentState("idle");
      return;
    }

    const controller = new AbortController();
    setHeroRecent(null);
    setHeroRecentState("loading");
    fetchDraftHeroRecent(canonicalMapId, controller.signal)
      .then((payload) => {
        setHeroRecent(payload);
        setHeroRecentState("ready");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setHeroRecent(null);
        setHeroRecentState("error");
      });

    return () => controller.abort();
  }, [match.canonical_map_id, draftRevision]);

  const heroRecentBySlot = React.useMemo(() => {
    const result = new Map<string, HeroRecentUseSummary | null>();
    for (const slot of heroRecent?.slots ?? []) {
      result.set(slotKey(slot.side, slot.position), slot.recent);
    }
    return result;
  }, [heroRecent]);

  const radiantSlots: HeroSlotData[] = React.useMemo(() => {
    if (!apiSlots || apiSlots.length === 0) return [];
    return apiSlots.filter((slot) => slot.side === "radiant").map((slot) => ({
      side: "radiant" as const,
      position: slot.position,
      playerName: slot.player_name || t("playerUnknown"),
      heroName: displayHeroName(slot.hero_id, slot.hero_name, locale, t("heroUnknown")),
      heroPicked: slot.hero_id != null,
      playerResolved: slot.canonical_player_id != null,
      heroRecent: heroRecentBySlot.get(slotKey("radiant", slot.position)) ?? null,
      heroRecentState,
    }));
  }, [apiSlots, heroRecentBySlot, heroRecentState, locale, t]);

  const direSlots: HeroSlotData[] = React.useMemo(() => {
    if (!apiSlots || apiSlots.length === 0) return [];
    return apiSlots.filter((slot) => slot.side === "dire").map((slot) => ({
      side: "dire" as const,
      position: slot.position,
      playerName: slot.player_name || t("playerUnknown"),
      heroName: displayHeroName(slot.hero_id, slot.hero_name, locale, t("heroUnknown")),
      heroPicked: slot.hero_id != null,
      playerResolved: slot.canonical_player_id != null,
      heroRecent: heroRecentBySlot.get(slotKey("dire", slot.position)) ?? null,
      heroRecentState,
    }));
  }, [apiSlots, heroRecentBySlot, heroRecentState, locale, t]);

  return (
    <div className="lineup-card">
      <div className="lineup-card-header">
        <div className="lineup-header-title">
          <span className="card-title">DRAFT LINEUP</span>
          <span className="subtitle">{locale === "zh-CN" ? "点击英雄查看当前可用的阵容身份与位置详情" : "Click a hero for current lineup identity and role details"}</span>
        </div>
      </div>

      <div className="lineup-teams-container">
        {radiantSlots.length === 0 && direSlots.length === 0 && <div className="empty-rail-msg">{t("noValidatedLineup")}</div>}
        <HeroSide side="radiant" teamName={sides?.radiant.name} slots={radiantSlots} locale={locale} onSelect={setSelectedSlot} />
        <div className="vs-divider-box"><span className="vs-txt">VS</span></div>
        <HeroSide side="dire" teamName={sides?.dire.name} slots={direSlots} locale={locale} onSelect={setSelectedSlot} />
      </div>

      {selectedSlot && (
        <div className="modal-backdrop" onClick={() => setSelectedSlot(null)}>
          <div className="modal-card mini-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>{selectedSlot.playerName} ({selectedSlot.heroName})</h3>
              <button className="close-btn" onClick={() => setSelectedSlot(null)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="slot-stat-row"><span>{locale === "zh-CN" ? "阵营" : "Side"}:</span><strong>{sideLabel(selectedSlot.side, locale, selectedSlot.side === "radiant" ? sides?.radiant.name : sides?.dire.name)}</strong></div>
              <div className="slot-stat-row"><span>{locale === "zh-CN" ? "位置" : "Role"}:</span><strong>{getPositionRole(selectedSlot.position)}</strong></div>
              <div className="slot-stat-row"><span>{locale === "zh-CN" ? "位置编号" : "Position"}:</span><strong>{getPositionLabel(selectedSlot.position)}</strong></div>
              <div className="slot-stat-row"><span>{locale === "zh-CN" ? "当前英雄近期战绩" : "Recent games on hero"}:</span><strong>{heroRecentLabel(selectedSlot.heroRecent, selectedSlot.heroRecentState, locale, selectedSlot.heroPicked, selectedSlot.playerResolved)}</strong></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

function HeroSide({ side, teamName, slots, locale, onSelect }: { side: "radiant" | "dire"; teamName?: string; slots: HeroSlotData[]; locale: string; onSelect: (slot: HeroSlotData) => void }) {
  return (
    <div className={`lineup-side ${side}-side`}>
      <div className={`side-label ${side === "radiant" ? "radiant-txt" : "dire-txt"}`}><span>{teamName ? `${teamName} · ` : ""}{side.toUpperCase()}</span></div>
      <div className="hero-slots-row">
        {slots.map((slot, index) => {
          const imgUrl = getHeroPortraitUrl(slot.heroName);
          return (
            <button type="button" key={`${side}-${slot.position}-${index}`} className="hero-slot-item" onClick={() => onSelect(slot)}>
              <div className="portrait-container">
                {imgUrl ? <img src={imgUrl} alt={slot.heroName} className="hero-portrait-img" onError={(event) => { event.currentTarget.style.display = "none"; }} /> : null}
                <div className="portrait-fallback">{slot.heroName.slice(0, 2).toUpperCase()}</div>
                <span className={`pos-badge ${side}`}>{getPositionLabel(slot.position || index + 1)}</span>
              </div>
              <div className="slot-meta">
                <span className="player-name">{slot.playerName}</span>
                <span className="hero-name">{slot.heroName}</span>
                <span className="hero-name">{heroRecentLabel(slot.heroRecent, slot.heroRecentState, locale, slot.heroPicked, slot.playerResolved)}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function slotKey(side: "radiant" | "dire", position: number): string {
  return `${side}:${position}`;
}

function displayHeroName(
  heroId: number | null,
  heroName: string | null,
  locale: string,
  notPickedLabel: string,
): string {
  if (heroName) return heroName;
  if (heroId === null) return notPickedLabel;
  return locale === "zh-CN" ? `英雄 #${heroId}` : `Hero #${heroId}`;
}

export function heroRecentLabel(
  recent: HeroRecentUseSummary | null,
  state: HeroRecentLoadState,
  locale: string,
  heroPicked = true,
  playerResolved = true,
): string {
  if (!heroPicked) {
    return locale === "zh-CN" ? "英雄未确定" : "Hero not picked";
  }
  if (!playerResolved) {
    return locale === "zh-CN" ? "选手身份未解析" : "Player identity unresolved";
  }
  if (state === "loading") {
    return locale === "zh-CN" ? "近期战绩加载中…" : "Loading recent hero games…";
  }
  if (state !== "ready" || recent === null) {
    return locale === "zh-CN" ? "近期数据不可用" : "Recent hero data unavailable";
  }
  if (recent.maps === 0) {
    return locale === "zh-CN" ? "近期无使用记录" : "No recent games on hero";
  }
  const record = `${recent.wins}–${recent.losses}`;
  const winRate = recent.win_rate === null ? null : Math.round(recent.win_rate * 100);
  if (locale === "zh-CN") {
    return winRate === null
      ? `近${recent.maps}场 · ${record}`
      : `近${recent.maps}场 ${winRate}% · ${record}`;
  }
  return winRate === null
    ? `Last ${recent.maps} · ${record}`
    : `Last ${recent.maps} ${winRate}% · ${record}`;
}

function sideLabel(side: "radiant" | "dire", locale: string, teamName?: string): string {
  const sideName = side === "radiant"
    ? (locale === "zh-CN" ? "天辉" : "Radiant")
    : (locale === "zh-CN" ? "夜魇" : "Dire");
  return teamName ? `${teamName} · ${sideName}` : sideName;
}
