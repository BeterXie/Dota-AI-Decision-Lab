import React from "react";
import type { AiDecision, MapDetail, MapSummary } from "../api";
import { useI18n } from "../i18n";

interface EvaluationCardProps {
  match: MapSummary | MapDetail;
}

interface AiPnlSummary {
  provider: string;
  model: string;
  pnl: number | null;
  stake: number | null;
  settledRounds: number;
  rounds: number;
}

export const EvaluationCard: React.FC<EvaluationCardProps> = ({ match }) => {
  const { locale, t } = useI18n();
  const detail = "result" in match ? match : null;
  const winnerId = detail?.result?.winner_team_id;
  const winner = winnerId === match.team_a?.id
    ? match.team_a?.name
    : winnerId === match.team_b?.id
      ? match.team_b?.name
      : null;
  const evidenceCount = detail?.result_evidence?.length || 0;
  const hasEvidence = evidenceCount > 0 || (detail?.future_odds?.length || 0) > 0 || detail?.result != null;
  const decisions = detail?.checkpoint_decisions ?? detail?.decisions ?? [];
  const pnlSummaries = summarizeVirtualPnl(decisions);

  return (
    <div className="analytics-card evaluation-card">
      <div className="card-header"><span className="card-title">{t("evaluation")}</span></div>
      <div className="eval-avg-row">
        <div className="avg-box">
          <span className="avg-val">{evidenceCount}</span>
          <span className="avg-lbl">{t("resultEvidence")}</span>
        </div>
        <div className="result-box">
          <span className="res-val">{winner || "—"}</span>
          <span className="res-lbl">{t("winner")}</span>
        </div>
      </div>
      {!hasEvidence && <div className="eval-footer-note">{t("noEvaluationEvidence")}</div>}
      {detail?.result?.provider_conflict && <div className="eval-footer-note">{t("resultConflict")}</div>}

      {pnlSummaries.length > 0 && (
        <div className="eval-pnl-section">
          <div className="eval-pnl-heading">
            <span>{locale === "zh-CN" ? "AI 虚拟投注结算（影子资金）" : "AI virtual bet settlement (shadow)"}</span>
          </div>
          {pnlSummaries.map((item) => (
            <div key={`${item.provider}:${item.model}`} className="eval-pnl-row">
              <div className="eval-pnl-ai">
                <strong>{providerLabel(item.provider)}</strong>
                <span>{item.model}</span>
              </div>
              <div className="eval-pnl-metric">
                <span>{locale === "zh-CN" ? "已结算盈亏" : "Settled P&L"}</span>
                <strong className={pnlTone(item.pnl)}>{formatSignedMoney(item.pnl, locale)}</strong>
              </div>
              <div className="eval-pnl-metric">
                <span>{locale === "zh-CN" ? "累计下注" : "Staked"}</span>
                <strong>{formatMoney(item.stake, locale)}</strong>
              </div>
              <div className="eval-pnl-metric">
                <span>{locale === "zh-CN" ? "回报率" : "ROI"}</span>
                <strong className={pnlTone(item.pnl)}>{formatRoi(item.pnl, item.stake, locale)}</strong>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

function summarizeVirtualPnl(decisions: AiDecision[]): AiPnlSummary[] {
  const groups = new Map<string, AiPnlSummary>();
  for (const decision of decisions) {
    const key = `${decision.provider}\u0000${decision.model}`;
    const item = groups.get(key) ?? {
      provider: decision.provider,
      model: decision.model,
      pnl: null,
      stake: null,
      settledRounds: 0,
      rounds: 0
    };
    const stake = toNumber(decision.stake ?? decision.decision?.stake);
    const pnl = toNumber(decision.evaluation?.virtual_pnl);
    if (stake != null) {
      item.stake = (item.stake ?? 0) + stake;
    }
    if (pnl != null) {
      item.pnl = (item.pnl ?? 0) + pnl;
      item.settledRounds += 1;
    }
    item.rounds += 1;
    groups.set(key, item);
  }
  return [...groups.values()].sort((a, b) => (b.pnl ?? 0) - (a.pnl ?? 0));
}

function toNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatMoney(value: number | null, locale: string): string {
  if (value == null) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

function formatSignedMoney(value: number | null, locale: string): string {
  if (value == null) return locale === "zh-CN" ? "未结算" : "Unsettled";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatMoney(value, locale)}`;
}

function formatRoi(pnl: number | null, stake: number | null, locale: string): string {
  if (pnl == null || stake == null || stake <= 0) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(pnl / stake);
}

function pnlTone(value: number | null): string {
  if (value == null) return "unsettled";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "flat";
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
