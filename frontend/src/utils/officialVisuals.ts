import type { MapSummary } from "../api";

type TeamIdentity = MapSummary["team_a"];

const VALVE_TEAM_LOGO_BASE = "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos";

const TEAM_NAME_TO_VALVE_ID: Record<string, string> = {
  "team liquid": "2163",
  liquid: "2163",
  "team spirit": "711938",
  spirit: "711938",
  "gaimin gladiators": "8599101",
  gladiators: "8599101",
  "betboom team": "8254400",
  betboom: "8254400",
  "xtreme gaming": "8261883",
  xtreme: "8261883",
  "aurora gaming": "8894263",
  aurora: "8894263",
  "team falcons": "9247354",
  falcons: "9247354",
  "tundra esports": "8255888",
  tundra: "8255888",
  og: "2586976",
  parivision: "9579040",
  "virtus.pro": "1883502",
  "virtus pro": "1883502",
  "lgd gaming": "15",
  lgd: "15",
  "team secret": "1838315",
  secret: "1838315",
  "natus vincere": "36",
  navi: "36",
  "azure ray": "8948704",
  "talon esports": "8567878",
  talon: "8567878",
  "boom esports": "7408018"
};

export interface OfficialEventArtwork {
  src: string;
  sourceName: string;
  sourceUrl: string;
  objectPosition?: string;
}

const VALVE_AEGIS: OfficialEventArtwork = {
  src: "https://cdn.steamstatic.com/apps/dota2/images//aegis/aegis_front.jpg",
  sourceName: "Valve / Dota 2",
  sourceUrl: "https://www.dota2.com/aegisofchampions",
  objectPosition: "50% 50%"
};

export function getOfficialTeamLogoUrl(team: TeamIdentity): string | null {
  if (!team) return null;
  const directId = team.id?.trim();
  if (directId && /^\d{1,12}$/.test(directId)) {
    return `${VALVE_TEAM_LOGO_BASE}/${directId}.png`;
  }

  const normalized = team.name?.trim().toLowerCase();
  if (!normalized) return null;
  for (const [name, teamId] of Object.entries(TEAM_NAME_TO_VALVE_ID)) {
    if (normalized === name || normalized.includes(name)) {
      return `${VALVE_TEAM_LOGO_BASE}/${teamId}.png`;
    }
  }
  return null;
}

export function getOfficialEventArtwork(eventName: string): OfficialEventArtwork | null {
  const normalized = eventName.trim().toLowerCase();
  if (
    normalized.includes("the international") ||
    normalized.includes("国际邀请赛") ||
    /(^|\s|-)ti\s*\d+/i.test(eventName)
  ) {
    return VALVE_AEGIS;
  }
  return null;
}

export function teamAbbreviation(team: TeamIdentity, fallbackName?: string): string {
  const name = team?.name?.trim() || fallbackName?.trim() || "TBD";
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return words.map((word) => word[0]).join("").slice(0, 3).toUpperCase();
  }
  return name.slice(0, 3).toUpperCase();
}
