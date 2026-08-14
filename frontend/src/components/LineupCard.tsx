import React, { useState } from "react";
import type { MapDetail, MapSummary } from "../api";
import { getHeroPortraitUrl, getPositionLabel, getPositionRole } from "../utils/dotaAssets";
import { resolveVerifiedMapSides } from "../utils/mapSides";
import { useI18n } from "../i18n";

interface LineupCardProps {
  match: MapSummary | MapDetail;
}

interface HeroSlotData {
  side: "radiant" | "dire";
  position: number;
  playerName: string;
  heroName: string;
}

export const LineupCard: React.FC<LineupCardProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const [selectedSlot, setSelectedSlot] = useState<HeroSlotData | null>(null);
  const apiSlots = match.draft?.slots;
  const sides = resolveVerifiedMapSides(match);

  const radiantSlots: HeroSlotData[] = React.useMemo(() => {
    if (!apiSlots || apiSlots.length === 0) return [];
    return apiSlots.filter((slot) => slot.side === "radiant").map((slot) => ({
      side: "radiant" as const,
      position: slot.position,
      playerName: slot.player_name || t("playerUnknown"),
      heroName: slot.hero_name || t("heroUnknown")
    }));
  }, [apiSlots, t]);

  const direSlots: HeroSlotData[] = React.useMemo(() => {
    if (!apiSlots || apiSlots.length === 0) return [];
    return apiSlots.filter((slot) => slot.side === "dire").map((slot) => ({
      side: "dire" as const,
      position: slot.position,
      playerName: slot.player_name || t("playerUnknown"),
      heroName: slot.hero_name || t("heroUnknown")
    }));
  }, [apiSlots, t]);

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
        <HeroSide side="radiant" teamName={sides?.radiant.name} slots={radiantSlots} onSelect={setSelectedSlot} />
        <div className="vs-divider-box"><span className="vs-txt">VS</span></div>
        <HeroSide side="dire" teamName={sides?.dire.name} slots={direSlots} onSelect={setSelectedSlot} />
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
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

function HeroSide({ side, teamName, slots, onSelect }: { side: "radiant" | "dire"; teamName?: string; slots: HeroSlotData[]; onSelect: (slot: HeroSlotData) => void }) {
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
              <div className="slot-meta"><span className="player-name">{slot.playerName}</span><span className="hero-name">{slot.heroName}</span></div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function sideLabel(side: "radiant" | "dire", locale: string, teamName?: string): string {
  const sideName = side === "radiant"
    ? (locale === "zh-CN" ? "天辉" : "Radiant")
    : (locale === "zh-CN" ? "夜魇" : "Dire");
  return teamName ? `${teamName} · ${sideName}` : sideName;
}
