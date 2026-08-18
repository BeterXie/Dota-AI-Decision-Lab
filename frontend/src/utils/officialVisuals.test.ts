import { describe, expect, it } from "vitest";
import { getOfficialEventArtwork, getOfficialTeamLogoUrl, teamAbbreviation } from "./officialVisuals";

describe("official visual assets", () => {
  it("prefers a numeric Valve team id when present", () => {
    expect(getOfficialTeamLogoUrl({ id: "2163", name: "Team Liquid" })).toBe(
      "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/2163.png"
    );
  });

  it("resolves known team names to the Valve team-logo CDN", () => {
    expect(getOfficialTeamLogoUrl({ id: "liquid", name: "Team Liquid" })).toBe(
      "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/2163.png"
    );
    expect(getOfficialTeamLogoUrl({ id: "spirit", name: "Team Spirit" })).toContain("/711938.png");
  });

  it("does not invent a third-party logo for unknown teams", () => {
    expect(getOfficialTeamLogoUrl({ id: "custom", name: "Unknown Stack" })).toBeNull();
    expect(teamAbbreviation({ id: "custom", name: "Unknown Stack" })).toBe("US");
  });

  it("uses Valve Aegis artwork only for The International family", () => {
    const ti = getOfficialEventArtwork("TI15 国际邀请赛");
    expect(ti?.sourceName).toBe("Valve / Dota 2");
    expect(ti?.src).toContain("cdn.steamstatic.com/apps/dota2/images/aegis/");
    expect(getOfficialEventArtwork("DreamLeague S24")).toBeNull();
  });
});
