import { describe, expect, it } from "vitest";

import { teamHref, teamSlugFromPath } from "./teams";

describe("team routes", () => {
  it("builds a stable team page href", () => {
    expect(teamHref("team-spirit")).toBe("/teams/team-spirit");
    expect(teamHref(null)).toBeNull();
  });

  it("reads the slug from a team page path", () => {
    expect(teamSlugFromPath("/teams/team-spirit")).toBe("team-spirit");
    expect(teamSlugFromPath("/teams/team-spirit/")).toBe("team-spirit");
    expect(teamSlugFromPath("/events")).toBeNull();
  });
});
