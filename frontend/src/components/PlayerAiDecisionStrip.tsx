import React, { useMemo, useState } from "react";
import type { AiDecision } from "../api";
import { useI18n } from "../i18n";

export function PlayerAiDecisionStrip({ decisions }: { decisions: AiDecision[] }) {
  const { locale, t } = useI18n();
  const [selected, setSelected] = useState<AiDecision | null>(null);
  const cards = useMemo(() => decisions.map((item) => ({ item, action: normalizeAction(item.decision?.action), fair: item.decision?.fair_probability_a ?? null, confidence: item.decision?.confidence ?? null })), [decisions]);
  const probabilities = cards.flatMap((card) => card.fair == null ? [] : [card.fair]);
  const min = probabilities.length ? Math.min(...probabilities) : null;
  const max = probabilities.length ? Math.max(...probabilities) : null;
  const spread = min == null || max == null ? null : (max - min) * 100;
  const counts = cards.reduce<Record<string, number>>((acc, card) => {
    acc[card.action] = (acc[card.action] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className="ai-decision-container player-ai-strip">
      <div className="player-section-heading">
        <div><span className="section-kicker">MULTI-AI</span><h3>{t("independentAiDecisions")}</h3></div>
        <div className="player-agreement-summary">
          {Object.entries(counts).map(([action, count]) => <span key={action}><b>{count}</b> {displayAction(action, locale)}</span>)}
        </div>
      </div>

      {cards.length ? (
        <div className="player-ai-cards">
          {cards.map(({ item, action, fair, confidence }) => (
            <button key={item.id} type="button" className={`player-ai-card ${actionTone(action)}`} onClick={() => setSelected(item)}>
              <div className="player-ai-model"><strong>{providerLabel(item.provider)}</strong><span>{item.model}</span></div>
              <div className={`player-ai-action ${actionTone(action)}`}>{displayAction(action, locale)}</div>
              <div className="player-ai-metrics">
                <div><span>{locale === "zh-CN" ? "A 公平概率" : "Fair A"}</span><strong>{formatPercent(fair, locale)}</strong></div>
                <div><span>{t("confidence")}</span><strong>{formatPercent(confidence, locale)}</strong></div>
              </div>
              <div className="confidence-track"><i style={{ width: `${Math.max(0, Math.min(100, (confidence ?? 0) * 100))}%` }} /></div>
            </button>
          ))}
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
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header"><h3>{providerLabel(selected.provider)} · {selected.model}</h3><button className="close-btn" onClick={() => setSelected(null)}>✕</button></div>
            <div className="modal-body">
              <ReasonList title={t("reasons")} values={selected.decision?.primary_reasons} />
              <ReasonList title={t("counterArguments")} values={selected.decision?.counter_arguments} />
              <ReasonList title={t("qualityConcerns")} values={selected.decision?.data_quality_concerns} />
              {selected.error && <div className="model-error">{selected.error}</div>}
              <div className="detail-section inline-meta"><span>{selected.model_version}</span><span>{selected.prompt_version}</span><span>{selected.latency_seconds == null ? "—" : `${selected.latency_seconds.toFixed(2)}s`}</span></div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function ReasonList({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return <div className="detail-section"><h4>{title}</h4><ul>{values.map((value, index) => <li key={`${index}-${value}`}>{value}</li>)}</ul></div>;
}

function normalizeAction(value: string | undefined): string {
  const normalized = (value ?? "INSUFFICIENT_DATA").trim().toUpperCase().replace(/\s+/g, "_");
  if (normalized === "BUY_A" || normalized === "BUY_B" || normalized === "NO_BUY" || normalized === "INSUFFICIENT_DATA") return normalized;
  return "INSUFFICIENT_DATA";
}

function displayAction(value: string, locale: string): string {
  const labels: Record<string, [string, string]> = { BUY_A: ["BUY A", "买 A"], BUY_B: ["BUY B", "买 B"], NO_BUY: ["NO BUY", "不买"], INSUFFICIENT_DATA: ["INSUFFICIENT", "数据不足"] };
  const label = labels[value] ?? labels.INSUFFICIENT_DATA;
  return locale === "zh-CN" ? label[1] : label[0];
}

function actionTone(value: string): string {
  if (value === "BUY_A") return "buy-a";
  if (value === "BUY_B") return "buy-b";
  if (value === "NO_BUY") return "no-buy";
  return "insufficient";
}

function providerLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("openai")) return "GPT";
  if (normalized.includes("anthropic")) return "Claude";
  if (normalized.includes("google") || normalized.includes("gemini")) return "Gemini";
  if (normalized.includes("deepseek")) return "DeepSeek";
  if (normalized.includes("kimi")) return "Kimi";
  return value;
}

function formatPercent(value: number | null, locale: string): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}
