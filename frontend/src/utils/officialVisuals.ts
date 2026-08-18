import type { MapSummary } from "../api";

type TeamIdentity = MapSummary["team_a"];

const VALVE_TEAM_LOGO_BASE = "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos";
const TI2026_ASSET_BASE = "https://cdn.steamstatic.com/apps/dota2/images/dota_react/international2026";
const TI2026_TEAM_LOGO_BASE = `${TI2026_ASSET_BASE}/teamlogos`;

// Valve's TI2026 page is the authoritative source for the teams competing in
// this event. Several organizations registered a different team ID this year,
// so the generic historical CDN path can show an obsolete crest.
const TI2026_TEAM_NAME_TO_ID: Record<string, string> = {
  "aurora": "9467224",
  "aurora gaming": "9467224",
  "boomboys": "8255888",
  "gamerlegion": "9964962",
  "huligani": "10149530",
  "iron wing": "10150413",
  "lgd": "10150538",
  "lgd gaming": "10150538",
  "nigma": "10136357",
  "nigma galaxy": "10136357",
  "og": "2586976",
  "team falcons": "9247354",
  "falcons": "9247354",
  "team liquid": "2163",
  liquid: "2163",
  "team resilience": "5017210",
  "team spirit": "7119388",
  spirit: "7119388",
  "team vision": "9572001",
  "team yandex": "9823272",
  "vici gaming": "726228",
  "xtreme": "8261500",
  "xtreme gaming": "8261500"
};

export interface OfficialEventArtwork {
  src: string;
  sourceName: string;
  sourceUrl: string;
  objectPosition?: string;
}

const TI2026_ARTWORK: OfficialEventArtwork = {
  src: `${TI2026_ASSET_BASE}/ti2026_logo.png`,
  sourceName: "Valve / Dota 2",
  sourceUrl: "https://www.dota2.com/esports/ti15/schedule",
  objectPosition: "50% 50%"
};

export function getValveTeamLogoUrl(teamId: string | number | null | undefined): string | null {
  if (teamId == null) return null;
  const normalized = String(teamId).trim();
  if (!/^\d{1,12}$/.test(normalized)) return null;
  return `${VALVE_TEAM_LOGO_BASE}/${normalized}.png`;
}

export function getOfficialTeamLogoUrl(team: TeamIdentity): string | null {
  if (!team) return null;
  const current = getOfficialTeamLogoUrlByName(team.name);
  if (current) return current;

  const direct = getValveTeamLogoUrl(team.id);
  if (direct) return direct;

  return null;
}

export function getOfficialTeamLogoUrlByName(
  teamName: string | null | undefined
): string | null {
  const normalized = teamName?.trim().toLowerCase().replace(/\s+/g, " ");
  if (!normalized) return null;
  const teamId = TI2026_TEAM_NAME_TO_ID[normalized];
  return teamId ? `${TI2026_TEAM_LOGO_BASE}/${teamId}.png` : null;
}

export function getOfficialEventArtwork(eventName: string): OfficialEventArtwork | null {
  return isTheInternational2026(eventName) ? TI2026_ARTWORK : null;
}

export function getOfficialEventDisplayName(eventName: string): string {
  const normalized = eventName.trim();
  if (!normalized) return "Dota 2";
  return isTheInternational2026(normalized) ? "The International 2026" : normalized;
}

export function teamAbbreviation(team: TeamIdentity, fallbackName?: string): string {
  const name = team?.name?.trim() || fallbackName?.trim() || "TBD";
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return words.map((word) => word[0]).join("").slice(0, 3).toUpperCase();
  }
  return name.slice(0, 3).toUpperCase();
}

export function eventAbbreviation(eventName: string): string {
  if (isTheInternational2026(eventName)) return "TI15";
  const ti = eventName.match(/TI\s*\d+/i);
  if (ti) return ti[0].replace(/\s+/g, "").toUpperCase();
  const words = eventName.match(/[A-Za-z0-9]+/g) ?? [];
  if (words.length >= 2) return words.map((word) => word[0]).join("").slice(0, 4).toUpperCase();
  return eventName.replace(/[^A-Za-z0-9\u4e00-\u9fff]/g, "").slice(0, 3).toUpperCase() || "D2";
}

function isTheInternational2026(eventName: string): boolean {
  const normalized = eventName.trim().toLowerCase().replace(/\s+/g, " ");
  return (
    normalized.includes("the international 2026") ||
    normalized.includes("international2026") ||
    /(^|[^a-z0-9])ti\s*15([^a-z0-9]|$)/i.test(normalized) ||
    /2026\s*国际邀请赛/.test(normalized)
  );
}
