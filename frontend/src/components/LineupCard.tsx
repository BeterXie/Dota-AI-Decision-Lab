import React, { useState } from "react";
import type { MapDetail, MapSummary } from "../api";
import { getHeroPortraitUrl, getPositionLabel, getPositionRole } from "../utils/dotaAssets";
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
  const { t } = useI18n();
  const [selectedSlot, setSelectedSlot] = useState<HeroSlotData | null>(null);

  const apiSlots = match.draft?.slots;

  const radiantSlots: HeroSlotData[] = React.useMemo(() => {
    if (!apiSlots || apiSlots.length === 0) return [];
    const items = apiSlots
      .filter((s) => s.side === "radiant")
      .map((s) => ({
        side: "radiant" as const,
        position: s.position,
        playerName: s.player_name || t("playerUnknown"),
        heroName: s.hero_name || t("heroUnknown")
      }));
    return items;
  }, [apiSlots, t]);

  const direSlots: HeroSlotData[] = React.useMemo(() => {
    if (!apiSlots || apiSlots.length === 0) return [];
    const items = apiSlots
      .filter((s) => s.side === "dire")
      .map((s) => ({
        side: "dire" as const,
        position: s.position,
        playerName: s.player_name || t("playerUnknown"),
        heroName: s.hero_name || t("heroUnknown")
      }));
    return items;
  }, [apiSlots, t]);

  return (
    <div className="lineup-card">
      <div className="lineup-card-header">
        <div className="lineup-header-title">
          <span className="card-title">DRAFT LINEUP</span>
          <span className="subtitle">Click hero for Player x Hero confidence stats</span>
        </div>
      </div>

      <div className="lineup-teams-container">
        {radiantSlots.length === 0 && direSlots.length === 0 && (
          <div className="empty-rail-msg">{t("noValidatedLineup")}</div>
        )}
        {/* RADIANT SIDE */}
        <div className="lineup-side radiant-side">
          <div className="side-label radiant-txt">
            <span>RADIANT</span>
          </div>

          <div className="hero-slots-row">
            {radiantSlots.map((slot, idx) => {
              const imgUrl = getHeroPortraitUrl(slot.heroName);
              const posTag = getPositionLabel(slot.position || idx + 1);

              return (
                <div
                  key={`rad-${idx}`}
                  className="hero-slot-item"
                  onClick={() => setSelectedSlot(slot)}
                >
                  <div className="portrait-container">
                    {imgUrl ? (
                      <img
                        src={imgUrl}
                        alt={slot.heroName}
                        className="hero-portrait-img"
                        onError={(e) => {
                          // Fallback if CDN image fails to load
                          (e.target as HTMLElement).style.display = "none";
                        }}
                      />
                    ) : null}
                    <div className="portrait-fallback">
                      {slot.heroName.slice(0, 2).toUpperCase()}
                    </div>
                    <span className="pos-badge radiant">{posTag}</span>
                  </div>

                  <div className="slot-meta">
                    <span className="player-name">{slot.playerName}</span>
                    <span className="hero-name">{slot.heroName}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="vs-divider-box">
          <span className="vs-txt">VS</span>
        </div>

        {/* DIRE SIDE */}
        <div className="lineup-side dire-side">
          <div className="side-label dire-txt">
            <span>DIRE</span>
          </div>

          <div className="hero-slots-row">
            {direSlots.map((slot, idx) => {
              const imgUrl = getHeroPortraitUrl(slot.heroName);
              const posTag = getPositionLabel(slot.position || idx + 1);

              return (
                <div
                  key={`dire-${idx}`}
                  className="hero-slot-item"
                  onClick={() => setSelectedSlot(slot)}
                >
                  <div className="portrait-container">
                    {imgUrl ? (
                      <img
                        src={imgUrl}
                        alt={slot.heroName}
                        className="hero-portrait-img"
                        onError={(e) => {
                          (e.target as HTMLElement).style.display = "none";
                        }}
                      />
                    ) : null}
                    <div className="portrait-fallback">
                      {slot.heroName.slice(0, 2).toUpperCase()}
                    </div>
                    <span className="pos-badge dire">{posTag}</span>
                  </div>

                  <div className="slot-meta">
                    <span className="player-name">{slot.playerName}</span>
                    <span className="hero-name">{slot.heroName}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Hero detail popover / modal */}
      {selectedSlot && (
        <div className="modal-backdrop" onClick={() => setSelectedSlot(null)}>
          <div className="modal-card mini-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {selectedSlot.playerName} ({selectedSlot.heroName})
              </h3>
              <button className="close-btn" onClick={() => setSelectedSlot(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div className="slot-stat-row">
                <span>Role:</span>
                <strong>{getPositionRole(selectedSlot.position)}</strong>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
