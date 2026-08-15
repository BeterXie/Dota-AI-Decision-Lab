import { describe, expect, test } from "vitest";
import type { MarketObservation } from "../api";
import { marketStageDisplayLabel, primaryMarketPair, targetProbability } from "./presentation";

const marketLeg = (overrides: Partial<MarketObservation>): MarketObservation => ({
  odds_id: 1,
  selection_team_id: "team-a",
  price: "1.80",
  fair_probability: 0.5,
  raw_status: 1,
  normalized_status: "UNKNOWN",
  metadata_version: "v1",
  market_type: "Winner",
  match_stage: "r2",
  received_at: "2026-08-15T05:00:00Z",
  age_seconds: 1,
  ...overrides
});

describe("marketStageDisplayLabel", () => {
  test("labels the deciding map final market as the map decider", () => {
    const zh = marketStageDisplayLabel(3, 3, "final", "zh-CN");
    expect(zh).toContain("第3局");
    expect(zh).toContain("决胜局");
    expect(zh).toContain("BO3");

    const en = marketStageDisplayLabel(3, 3, "final", "en");
    expect(en).toContain("Map 3 (decider)");
  });

  test("labels ordinary map stages without the BO3 note", () => {
    expect(marketStageDisplayLabel(2, 3, "r2", "zh-CN")).toBe("第2局");
    expect(marketStageDisplayLabel(2, 3, "Map 2", "en")).toBe("Map 2");
  });

  test("keeps unknown stages explicit", () => {
    expect(marketStageDisplayLabel(null, null, null, "zh-CN")).toBe("未知盘口");
    expect(marketStageDisplayLabel(null, null, null, "en")).toBe("Unknown market stage");
  });
});

describe("primaryMarketPair", () => {
  test("returns the selected stage next to the pair legs", () => {
    const aFinal = marketLeg({ odds_id: 10, selection_team_id: "team-a", match_stage: "final" });
    const bFinal = marketLeg({ odds_id: 11, selection_team_id: "team-b", match_stage: "final" });

    const pair = primaryMarketPair([aFinal, bFinal], "team-a", "team-b");

    expect(pair?.teamA.odds_id).toBe(10);
    expect(pair?.teamB.odds_id).toBe(11);
    expect(pair?.stage).toBe("final");
  });

  test("prefers a map-stage winner pair over the series final pair", () => {
    const aMap = marketLeg({ odds_id: 20, selection_team_id: "team-a", match_stage: "r3" });
    const bMap = marketLeg({ odds_id: 21, selection_team_id: "team-b", match_stage: "r3" });
    const aFinal = marketLeg({ odds_id: 10, selection_team_id: "team-a", match_stage: "final" });
    const bFinal = marketLeg({ odds_id: 11, selection_team_id: "team-b", match_stage: "final" });

    const pair = primaryMarketPair([aFinal, bFinal, aMap, bMap], "team-a", "team-b");

    expect(pair?.stage).toBe("r3");
    expect(pair?.teamA.odds_id).toBe(20);
  });
});



describe("targetProbability", () => {
  test("returns Team A probability for BUY_A and other non-B actions", () => {
    expect(targetProbability("BUY_A", 0.35)).toBe(0.35);
    expect(targetProbability("NO_BUY", 0.35)).toBe(0.35);
  });

  test("inverts Team A probability for BUY_B", () => {
    expect(targetProbability("BUY_B", 0.35)).toBeCloseTo(0.65);
  });

  test("keeps missing values missing", () => {
    expect(targetProbability("BUY_B", null)).toBeNull();
    expect(targetProbability("BUY_B", undefined)).toBeNull();
  });
});
