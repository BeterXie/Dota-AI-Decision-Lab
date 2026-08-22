import { describe, expect, it } from "vitest";
import { predictionPolicyLabel, presentPredictionCopy } from "./predictionCopy";

describe("prediction copy presentation", () => {
  it("normalizes legacy virtual-money language without changing stored data", () => {
    expect(presentPredictionCopy(
      "盈亏平衡概率约92.6%，考虑`virtual_bankroll.locked_balance`已有250单位未结算头寸，本次仅追加有限仓位。"
    )).toBe("市场参考概率约92.6%，考虑已有250 点待结算预测积分，本次仅增加有限预测积分。");

    expect(presentPredictionCopy(
      "The bankroll supports a small stake, but the break-even probability leaves no reason to buy."
    )).toBe("The points balance supports a small amount of prediction points, but the market reference probability leaves no reason to predict.");

    expect(presentPredictionCopy("模拟本金、预期收益率和最大回撤")).toBe("预测积分、预计积分变化率和最大积分回落");
  });

  it("presents legacy policy identifiers with points terminology", () => {
    expect(predictionPolicyLabel("shadow-tournament-portfolio-v3")).toBe("points-tournament-portfolio-v3");
  });
});
