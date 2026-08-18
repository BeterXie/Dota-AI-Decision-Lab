import { describe, expect, it } from "vitest";
import {
  getOfficialEventArtwork,
  getOfficialEventDisplayName,
  getOfficialTeamLogoUrl,
  teamAbbreviation
} from "./officialVisuals";

describe("official visual assets", () => {
  it("prefers the current Valve event asset over a legacy numeric id", () => {
    expect(getOfficialTeamLogoUrl({ id: "15", name: "LGD Gaming" })).toBe(
      "https://cdn.steamstatic.com/apps/dota2/images/dota_react/international2026/teamlogos/10150538.png"
    );
  });

  it("resolves TI2026 teams to the official Valve event assets", () => {
    expect(getOfficialTeamLogoUrl({ id: "liquid", name: "Team Liquid" })).toBe(
      "https://cdn.steamstatic.com/apps/dota2/images/dota_react/international2026/teamlogos/2163.png"
    );
    expect(getOfficialTeamLogoUrl({ id: "spirit", name: "Team Spirit" })).toContain("/7119388.png");
    expect(getOfficialTeamLogoUrl({ id: "aurora", name: "Aurora" })).toContain("/9467224.png");
    expect(getOfficialTeamLogoUrl({ id: "nigma", name: "Nigma Galaxy" })).toContain("/10136357.png");
  });

  it("does not invent a third-party logo for unknown teams", () => {
    expect(getOfficialTeamLogoUrl({ id: "custom", name: "Unknown Stack" })).toBeNull();
    expect(teamAbbreviation({ id: "custom", name: "Unknown Stack" })).toBe("US");
  });

  it("uses the current Valve event logo only for The International 2026", () => {
    const ti = getOfficialEventArtwork("TI15 国际邀请赛");
    expect(ti?.sourceName).toBe("Valve / Dota 2");
    expect(ti?.src).toContain("international2026/ti2026_logo.png");
    expect(getOfficialEventDisplayName("TI15 国际邀请赛")).toBe("The International 2026");
    expect(getOfficialEventArtwork("The International 2025")).toBeNull();
    expect(getOfficialEventArtwork("DreamLeague S24")).toBeNull();
  });
});
