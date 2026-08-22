const REPLACEMENTS: Array<[RegExp, string]> = [
  [/`virtual_bankroll\.locked_balance`\s*已有/gi, "已有"],
  [/`virtual_bankroll\.[^`]+`/gi, "积分记录"],
  [/盈亏平衡概率/g, "市场参考概率"],
  [/盈亏平衡/g, "市场参考"],
  [/预期收益/g, "预计积分变化"],
  [/收益率/g, "积分变化率"],
  [/盈亏/g, "积分变化"],
  [/收益/g, "积分变化"],
  [/回撤/g, "积分回落"],
  [/模拟本金/g, "预测积分"],
  [/本金/g, "初始积分"],
  [/正期望空间/g, "正向积分空间"],
  [/继续买入/g, "继续预测"],
  [/([\d,.]+)\s*单位未结算头寸/g, "$1 点待结算预测积分"],
  [/未结算头寸/g, "待结算预测积分"],
  [/追加([\d,.]+)\s*单位/g, "增加 $1 点预测积分"],
  [/追加有限仓位/g, "增加有限预测积分"],
  [/投入小额虚拟资金/g, "使用少量预测积分"],
  [/投入规模/g, "预测积分规模"],
  [/虚拟资金/g, "预测积分"],
  [/模拟资金/g, "预测积分"],
  [/仓位/g, "预测积分"],
  [/头寸/g, "预测记录"],
  [/买入/g, "预测"],
  [/下注/g, "预测"],
  [/投注/g, "预测"],
  [/\bbreak-even probability\b/gi, "market reference probability"],
  [/\bbreak-even\b/gi, "market reference"],
  [/\bexpected returns?\b/gi, "expected points change"],
  [/\breturn on investment\b/gi, "points change rate"],
  [/\bprofit and loss\b/gi, "points change"],
  [/\bprofit\s*\/\s*loss\b/gi, "points change"],
  [/\bdrawdown\b/gi, "points decline"],
  [/\bsimulated capital\b/gi, "prediction points balance"],
  [/\binitial capital\b/gi, "initial points"],
  [/\breturns\b/gi, "points change"],
  [/\bpositive expected value\b/gi, "positive points margin"],
  [/\bvirtual bankroll\b/gi, "prediction points balance"],
  [/\bbankroll\b/gi, "points balance"],
  [/\ba small stake\b/gi, "a small amount of prediction points"],
  [/\bsmall stake\b/gi, "a small amount of prediction points"],
  [/\bstakes?\b/gi, "prediction points"],
  [/\bpositions?\b/gi, "prediction records"],
  [/\bbuying\b/gi, "predicting"],
  [/\bbuy\b/gi, "predict"],
  [/\bbetting\b/gi, "prediction"],
  [/\bbets?\b/gi, "predictions"],
  [/\bwagers?\b/gi, "predictions"],
  [/\bP&L\b/gi, "points change"],
  [/\bROI\b/gi, "points change rate"]
];

export function presentPredictionCopy(value: string): string {
  return REPLACEMENTS.reduce(
    (copy, [pattern, replacement]) => copy.replace(pattern, replacement),
    value
  );
}

export function predictionPolicyLabel(value: string): string {
  return value.replace(/shadow/gi, "points");
}
