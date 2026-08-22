import React, { useMemo, useState } from "react";
import type { AiDecision } from "../api";
import { useI18n } from "../i18n";
import { presentPredictionCopy } from "../utils/predictionCopy";

interface AiDecisionGroup {
  key: string;
  provider: string;
  model: string;
  rounds: AiDecision[];
  latest: AiDecision;
}

export function PlayerAiDecisionStrip({
  decisions,
  embedded = false
}: {
  decisions: AiDecision[];
  embedded?: boolean;
}) {
  const { locale, t } = useI18n();
  const [selected, setSelected] = useState<AiDecisionGroup | null>(null);
  const groups = useMemo(() => groupByAi(decisions), [decisions]);
  const summaries = useMemo(
    () => groups.map((group) => summaryFor(group)),
    [groups]
  );
  const probabilities = summaries.flatMap((summary) => summary.fair == null ? [] : [summary.fair]);
  const min = probabilities.length ? Math.min(...probabilities) : null;
  const max = probabilities.length ? Math.max(...probabilities) : null;
  const spread = min == null || max == null ? null : (max - min) * 100;
  const counts = summaries.reduce<Record<string, number>>((acc, summary) => {
    acc[summary.action] = (acc[summary.action] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className={`ai-decision-container player-ai-strip${embedded ? " player-ai-strip-embedded" : ""}`}>
      {!embedded && (
        <div className="player-section-heading">
          <div><span className="section-kicker">MULTI-AI</span><h3>{t("independentAiDecisions")}</h3></div>
          <div className="player-agreement-summary">
            {Object.entries(counts).map(([action, count]) => <span key={action}><b>{count}</b> {displayAction(action, locale)}</span>)}
          </div>
        </div>
      )}

      {groups.length ? (
        <div className="player-ai-cards">
          {groups.map((group) => {
            const summary = summaryFor(group);
            return (
              <button key={group.key} type="button" className={`player-ai-card ${actionTone(summary.action)}`} onClick={() => setSelected(group)}>
                <div className="player-ai-model">
                  <strong>{providerLabel(group.provider)}</strong>
                  <span>{group.model}</span>
                </div>
                <div className="player-ai-rounds-badge">
                  {group.rounds.length === 1
                    ? locale === "zh-CN" ? "1 轮预测" : "1 prediction round"
                    : locale === "zh-CN" ? `${group.rounds.length} 轮预测` : `${group.rounds.length} prediction rounds`}
                </div>
                <div className="player-ai-checkpoint">
                  {locale === "zh-CN" ? "最新预测 · " : "Latest prediction · "}
                  {formatCheckpoint(group.latest.snapshot_decision_at, group.latest.snapshot_mode, locale, false)}
                </div>
                <div className={`player-ai-action ${actionTone(summary.action)}`} style={actionStyle(summary.action)}>{displayAction(summary.action, locale)}</div>
                <div className="player-ai-metrics">
                  <div><span>{locale === "zh-CN" ? "A 公平概率" : "Fair A"}</span><strong>{formatPercent(summary.fair, locale)}</strong></div>
                  <div><span>{t("confidence")}</span><strong>{formatPercent(summary.confidence, locale)}</strong></div>
                </div>
                <div className="player-ai-bankroll">
                  <div><span>{locale === "zh-CN" ? "本轮预测积分" : "Prediction points"}</span><strong>{formatPoints(summary.stake, locale)}</strong></div>
                  <div><span>{locale === "zh-CN" ? "可用积分" : "Available points"}</span><strong>{formatPoints(summary.bankrollBefore, locale)}</strong></div>
                </div>
                <div className={`player-ai-pnl ${pnlTone(summary.settledPnl)}`}>
                  <span>{locale === "zh-CN" ? "已结算积分变化" : "Settled points change"}</span>
                  <strong>{formatSignedPoints(summary.settledPnl, locale)}</strong>
                </div>
                <div className="confidence-track"><i style={{ width: `${Math.max(0, Math.min(100, (summary.confidence ?? 0) * 100))}%` }} /></div>
              </button>
            );
          })}
        </div>
      ) : <div className="empty-rail-msg">{t("noAiDecisions")}</div>}

      <div className="player-ai-footer">
        <span>{locale === "zh-CN" ? "A 队公平概率区间" : "Fair probability A range"}</span>
        <strong>{min == null || max == null ? "—" : `${formatPercent(min, locale)} – ${formatPercent(max, locale)}`}</strong>
        <span>{locale === "zh-CN" ? "模型分歧" : "Spread"}</span>
        <strong>{spread == null ? "—" : `${spread.toFixed(1)}pp`}</strong>
      </div>

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal-card ai-rounds-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>{providerLabel(selected.provider)} · {selected.model}</h3>
              <button className="close-btn" type="button" onClick={() => setSelected(null)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="ai-bankroll-summary">
                <div><span>{locale === "zh-CN" ? "初始预测积分" : "Initial prediction points"}</span><strong>{formatPoints(initialBankroll(selected), locale)}</strong></div>
                <div><span>{locale === "zh-CN" ? "累计预测积分" : "Total prediction points"}</span><strong>{formatPoints(totalStaked(selected), locale)}</strong></div>
                <div><span>{locale === "zh-CN" ? "已结算积分变化" : "Settled points change"}</span><strong className={pnlTone(settledPnl(selected))}>{formatSignedPoints(settledPnl(selected), locale)}</strong></div>
                  {pendingStake(selected) != null && pendingStake(selected)! > 0 && (
                    <div><span>{locale === "zh-CN" ? "待结算预测积分" : "Pending prediction points"}</span><strong>{formatPoints(pendingStake(selected), locale)}</strong></div>
                  )}
                  {finalBankroll(selected) == null && (
                    <div><span>{locale === "zh-CN" ? "当前可用积分" : "Current available points"}</span><strong>{formatPoints(availableBankroll(selected), locale)}</strong></div>
                  )}
                {finalBankroll(selected) != null && (
                    <div><span>{locale === "zh-CN" ? "最终积分" : "Final points"}</span><strong>{formatPoints(finalBankroll(selected), locale)}</strong></div>
                  )}
              </div>
              <div className="ai-round-timeline">
                {selected.rounds.map((item, index) => {
                  const action = normalizeAction(item.decision?.action);
                  const stake = numberOrNull(item.stake ?? item.decision?.stake);
                  const before = numberOrNull(item.bankroll_before);
                  const after = before == null ? null : before - (stake ?? 0);
                  return (
                    <article key={item.snapshot_id ?? item.id} className={`ai-round ${actionTone(action)}`}>
                      <header className="ai-round-header">
                        <span className="ai-round-index">#{index + 1}</span>
                        <span className="ai-round-checkpoint">{formatCheckpoint(item.snapshot_decision_at, item.snapshot_mode, locale)}</span>
                        <span className={`player-ai-action ${actionTone(action)}`} style={actionStyle(action)}>{displayAction(action, locale)}</span>
                      </header>
                      <div className="ai-round-metrics">
                        <div><span>{locale === "zh-CN" ? "A 公平概率" : "Fair A"}</span><strong>{formatPercent(numberOrNull(item.decision?.fair_probability_a), locale)}</strong></div>
                        <div><span>{t("confidence")}</span><strong>{formatPercent(numberOrNull(item.decision?.confidence), locale)}</strong></div>
                        <div><span>{locale === "zh-CN" ? "市场判断" : "Market view"}</span><strong>{item.decision?.market_assessment ?? "—"}</strong></div>
                        <div><span>{locale === "zh-CN" ? "A 市场参考下限" : "Min market reference A"}</span><strong>{item.decision?.minimum_acceptable_odds_a ?? "—"}</strong></div>
                        <div><span>{locale === "zh-CN" ? "预测积分" : "Prediction points"}</span><strong>{formatPoints(stake, locale)}</strong></div>
                        <div><span>{locale === "zh-CN" ? "积分余额" : "Points balance"}</span><strong>{before == null ? "—" : `${formatPoints(before, locale)} → ${formatPoints(after, locale)}`}</strong></div>
                        <div><span>{locale === "zh-CN" ? "积分结算倍率" : "Points settlement multiplier"}</span><strong>{item.evaluation?.virtual_odds == null ? (locale === "zh-CN" ? "未结算" : "Unsettled") : item.evaluation.virtual_odds.toFixed(2)}</strong></div>
                        <div><span>{locale === "zh-CN" ? "积分变化" : "Points change"}</span><strong className={pnlTone(numberOrNull(item.evaluation?.virtual_pnl))}>{formatSignedPoints(numberOrNull(item.evaluation?.virtual_pnl), locale)}</strong></div>
                      </div>
                      <div className="confidence-track"><i style={{ width: `${Math.max(0, Math.min(100, (numberOrNull(item.decision?.confidence) ?? 0) * 100))}%` }} /></div>
                      {item.error && <div className="model-error">{item.error}</div>}
                      <ReasonList title={t("reasons")} values={item.decision?.primary_reasons} />
                      <div className="detail-section inline-meta">
                        <span>{item.model_version}</span>
                        <span>{item.prompt_version}</span>
                          <span>{item.latency_seconds == null ? "—" : `inference ${item.latency_seconds.toFixed(2)}s`}</span>
                          <span>
                            {formatDuration(item.job_enqueued_at, item.job_claimed_at, "queue")}
                          </span>
                          <span>
                            {formatDuration(item.job_enqueued_at, item.decision_persisted_at, "end-to-end")}
                          </span>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function groupByAi(decisions: AiDecision[]): AiDecisionGroup[] {
  const byKey = new Map<string, AiDecisionGroup>();
  for (const item of decisions) {
    const key = `${item.provider}\u0000${item.model}`;
    let group = byKey.get(key);
    if (!group) {
      group = { key, provider: item.provider, model: item.model, rounds: [], latest: item };
      byKey.set(key, group);
    }
    const roundKey = item.snapshot_id ?? item.id;
    const existingIndex = group.rounds.findIndex((round) => (round.snapshot_id ?? round.id) === roundKey);
    if (existingIndex >= 0) {
      const existing = group.rounds[existingIndex];
      const replacementWins = item.request_started_at > existing.request_started_at;
      if (replacementWins) group.rounds[existingIndex] = item;
    } else {
      group.rounds.push(item);
    }
  }
  const groups = [...byKey.values()];
  for (const group of groups) {
    group.rounds.sort((a, b) => decisionTime(b) - decisionTime(a));
    group.latest = group.rounds[0];
  }
  groups.sort((a, b) => a.provider.localeCompare(b.provider) || a.model.localeCompare(b.model));
  return groups;
}

function summaryFor(group: AiDecisionGroup) {
  const item = group.latest;
  return {
    action: normalizeAction(item.decision?.action),
    fair: numberOrNull(item.decision?.fair_probability_a),
    confidence: numberOrNull(item.decision?.confidence),
    stake: numberOrNull(item.stake ?? item.decision?.stake),
    bankrollBefore: numberOrNull(item.bankroll_before),
    settledPnl: settledPnl(group)
  };
}

function decisionTime(item: AiDecision): number {
  const snapshotTime = item.snapshot_decision_at ? Date.parse(item.snapshot_decision_at) : NaN;
  if (Number.isFinite(snapshotTime)) return snapshotTime;
  const requestTime = Date.parse(item.request_started_at);
  return Number.isFinite(requestTime) ? requestTime : 0;
}


function formatDuration(start: string | null | undefined, end: string | null | undefined, label: string): string {
  if (!start || !end) return `${label} —`;
  const seconds = (Date.parse(end) - Date.parse(start)) / 1000;
  return Number.isFinite(seconds) ? `${label} ${seconds.toFixed(2)}s` : `${label} —`;
}

function numberOrNull(value: number | string | null | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function initialBankroll(group: AiDecisionGroup): number | null {
  const firstWithBankroll = [...group.rounds].reverse().find((item) => numberOrNull(item.bankroll_before) != null);
  return firstWithBankroll ? numberOrNull(firstWithBankroll.bankroll_before) : null;
}

function totalStaked(group: AiDecisionGroup): number | null {
  let total = 0;
  let found = false;
  for (const item of group.rounds) {
    const stake = numberOrNull(item.stake ?? item.decision?.stake);
    if (stake != null) {
      total += stake;
      found = true;
    }
  }
  return found ? total : null;
}

function settledPnl(group: AiDecisionGroup): number | null {
  let total = 0;
  let found = false;
  for (const item of group.rounds) {
    const pnl = numberOrNull(item.evaluation?.virtual_pnl);
    if (pnl != null) {
      total += pnl;
      found = true;
    }
  }
  return found ? total : null;
}

function finalBankroll(group: AiDecisionGroup): number | null {
  const initial = initialBankroll(group);
  if (initial == null) return null;

  const pnl = settledPnl(group) ?? 0;
  if (pendingStake(group) != null && pendingStake(group)! > 0) return null;
  return initial + pnl;
}

function pendingStake(group: AiDecisionGroup): number | null {
  let total = 0;
  let found = false;
  for (const item of group.rounds) {
    const stake = numberOrNull(item.stake ?? item.decision?.stake);
    if (stake == null || stake <= 0) continue;
    if (numberOrNull(item.evaluation?.virtual_pnl) != null) continue;
    total += stake;
    found = true;
  }
  return found ? total : null;
}

function availableBankroll(group: AiDecisionGroup): number | null {
  const initial = initialBankroll(group);
  if (initial == null) return null;
  return initial - (totalStaked(group) ?? 0);
}

function ReasonList({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return <div className="detail-section"><h4>{title}</h4><ul>{values.map((value, index) => <li key={`${index}-${value}`}>{presentPredictionCopy(value)}</li>)}</ul></div>;
}

function normalizeAction(value: string | undefined): string {
  const normalized = (value ?? "INSUFFICIENT_DATA").trim().toUpperCase().replace(/\s+/g, "_");
  if (normalized === "BUY_A" || normalized === "BUY_B" || normalized === "NO_BUY" || normalized === "INSUFFICIENT_DATA") return normalized;
  return "INSUFFICIENT_DATA";
}

function displayAction(value: string, locale: string): string {
  const labels: Record<string, [string, string]> = { BUY_A: ["PREDICT A", "预测 A"], BUY_B: ["PREDICT B", "预测 B"], NO_BUY: ["NO PREDICTION", "暂不预测"], INSUFFICIENT_DATA: ["INSUFFICIENT", "数据不足"] };
  const label = labels[value] ?? labels.INSUFFICIENT_DATA;
  return locale === "zh-CN" ? label[1] : label[0];
}

function actionTone(value: string): string {
  if (value === "BUY_A") return "buy-a";
  if (value === "BUY_B") return "buy-b";
  if (value === "NO_BUY") return "no-buy";
  return "insufficient";
}

function actionStyle(value: string): React.CSSProperties | undefined {
  if (value === "BUY_A") return { color: "#7C9CFF", background: "rgba(124,156,255,.10)" };
  if (value === "BUY_B") return { color: "#9C82FF", background: "rgba(156,130,255,.10)" };
  return undefined;
}

function providerLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("local_openai")) return "Local GPT";
  if (normalized.includes("openai")) return "GPT";
  if (normalized.includes("anthropic")) return "Claude";
  if (normalized.includes("google") || normalized.includes("gemini")) return "Gemini";
  if (normalized.includes("deepseek")) return "DeepSeek";
  if (normalized.includes("kimi")) return "Kimi";
  return value;
}

function formatCheckpoint(value: string | undefined, mode: string | undefined, locale: string, includeLabel = true): string {
  if (!value) return mode || (locale === "zh-CN" ? "历史预测" : "Previous prediction");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return mode ?? "";
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const suffix = mode ? ` · ${mode}` : "";
  if (!includeLabel) return `${time}${suffix}`;
  return locale === "zh-CN" ? `预测时点 · ${time}${suffix}` : `Prediction time · ${time}${suffix}`;
}

function formatPercent(value: number | null, locale: string): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function formatPoints(value: number | null, locale: string): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

function formatSignedPoints(value: number | null, locale: string): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)}`;
}

function pnlTone(value: number | null): string {
  if (value == null) return "unsettled";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "flat";
}
