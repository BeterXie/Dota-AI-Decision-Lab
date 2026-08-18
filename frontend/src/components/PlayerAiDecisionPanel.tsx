import React, { useEffect, useMemo, useState } from "react";
import type { AiDecision } from "../api";
import { useI18n } from "../i18n";
import type { AiAccessState } from "./AppShell";
import { PlayerAiDecisionStrip } from "./PlayerAiDecisionStrip";

interface SnapshotDecisionPayload {
  decisions?: AiDecision[];
}

const CURRENT_ATTEMPT_REFRESH_MS = 4_000;

export function PlayerAiDecisionPanel({
  decisions,
  currentSnapshotId,
  access,
  analysisAvailable,
  completedModels,
  onLogin
}: {
  decisions: AiDecision[];
  currentSnapshotId?: string | null;
  access: AiAccessState;
  analysisAvailable: boolean;
  completedModels: number;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const [attempts, setAttempts] = useState<AiDecision[]>([]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    // Snapshot detail remains a global diagnostics surface. SERIES/MAP
    // access receives the authorized decisions from the map premium endpoint
    // and must not accidentally poll the cross-product snapshot API.
    if (!access.entitled || access.scope !== "GLOBAL" || !currentSnapshotId) {
      setAttempts([]);
      return () => { cancelled = true; };
    }

    const refresh = async () => {
      try {
        const response = await fetch(`/api/snapshots/${currentSnapshotId}`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" }
        });
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        const payload = await response.json() as SnapshotDecisionPayload;
        if (!cancelled) setAttempts(latestAttempts(payload.decisions ?? []));
      } catch {
        if (!cancelled) setAttempts([]);
      } finally {
        if (!cancelled) timer = window.setTimeout(refresh, CURRENT_ATTEMPT_REFRESH_MS);
      }
    };

    void refresh();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [access.entitled, access.scope, currentSnapshotId]);

  const latest = useMemo(() => latestAttempts(attempts), [attempts]);

  if (!access.entitled) {
    return (
      <section className="analytics-card ai-decision-container" aria-label="AI Decision access">
        <div className="player-section-heading">
          <div>
            <span className="section-kicker">AI INTELLIGENCE</span>
            <h3>{locale === "zh-CN" ? "AI 实时决策" : "Live AI decisions"}</h3>
          </div>
          <span className="trust-pill degraded">LOCKED</span>
        </div>
        <div className="player-agreement-summary">
          <span>
            {analysisAvailable
              ? locale === "zh-CN"
                ? `AI 分析已生成${completedModels > 0 ? ` · ${completedModels} 个模型已完成` : ""}`
                : `AI analysis is ready${completedModels > 0 ? ` · ${completedModels} models completed` : ""}`
              : locale === "zh-CN"
                ? "AI 正在等待满足决策条件"
                : "AI is waiting for decision conditions"}
          </span>
          <span>
            {locale === "zh-CN"
                ? "可以购买当前 BO 系列赛或所属赛事的 Pass。方向、置信度、公允概率、下注建议与推理只在有效权限范围内开放。"
                : "Buy the current BO series or its event pass. Direction, confidence, fair probability, staking and reasoning stay inside the purchased access scope."}
          </span>
        </div>
        {!access.authenticated && access.authEnabled && (
          <button className="auth-primary-btn" type="button" onClick={onLogin}>
            {locale === "zh-CN" ? "登录查看 AI 权限" : "Sign in for AI access"}
          </button>
        )}
        {access.authenticated && (
          <>
            <div className="auth-error" role="status">
              {locale === "zh-CN"
                ? "当前账号尚未拥有这场比赛的 AI Decision 权限。"
                : "This account does not have AI Decision access for this match."}
            </div>
            <a className="auth-primary-btn" href={access.upgradeHref}>
              {locale === "zh-CN" ? "查看当前比赛 Pass" : "View competition pass"}
            </a>
          </>
        )}
        {!access.authEnabled && (
          <div className="auth-error" role="status">
            {locale === "zh-CN"
              ? "当前运行环境尚未启用登录，因此付费 AI 接口保持关闭。"
              : "Authentication is disabled in this runtime, so premium AI access remains closed."}
          </div>
        )}
      </section>
    );
  }

  return (
    <>
      {access.scope !== "GLOBAL" && access.scope !== "FREE" && access.scope !== "POSTMATCH" && (
        <section className="analytics-card ai-decision-container" aria-label="Scoped AI access">
          <div className="player-agreement-summary">
            <span>
              {locale === "zh-CN"
                ? `当前 AI 权限范围：${access.scope === "EVENT" ? "本赛事" : access.scope === "SERIES" ? "本 BO 系列赛" : "本局 Map"}`
                : `Current AI access scope: ${access.scope === "EVENT" ? "this event" : access.scope === "SERIES" ? "this BO series" : "this map"}`}
            </span>
          </div>
        </section>
      )}
      {access.scope === "FREE" && (
        <section className="analytics-card ai-decision-container" aria-label="Free group stage access">
          <div className="player-agreement-summary">
            <span>{locale === "zh-CN" ? "小组赛 AI 决策已对 Free 开放" : "Group-stage AI decisions are open on Free Access"}</span>
          </div>
        </section>
      )}
      {access.scope === "POSTMATCH" && (
        <section className="analytics-card ai-decision-container" aria-label="Post-match public access">
          <div className="player-agreement-summary">
            <span>{locale === "zh-CN" ? "比赛已结束，AI 决策数据对所有用户公开" : "The match is over; AI decisions are public to everyone"}</span>
          </div>
        </section>
      )}
      {latest.length > 0 && (
        <section className="ai-decision-container player-ai-current-experiments" aria-label="Current AI experiment status">
          <div className="player-section-heading">
            <div>
              <span className="section-kicker">CURRENT</span>
              <h3>{locale === "zh-CN" ? "当前实验状态" : "Current experiment status"}</h3>
            </div>
          </div>
          <div className="player-agreement-summary">
            {latest.map((item) => (
              <span key={`${item.provider}:${item.model}`} className={item.parse_status === "SUCCESS" ? "" : "model-error"}>
                <b>{providerLabel(item.provider)}</b> {item.parse_status} · {item.prompt_version}
                {item.error ? ` · ${item.error}` : ""}
              </span>
            ))}
          </div>
        </section>
      )}
      {access.loading && decisions.length === 0 ? (
        <section className="analytics-card ai-decision-container">
          <div className="empty-rail-msg">
            {locale === "zh-CN" ? "正在读取 AI 决策…" : "Loading AI decisions…"}
          </div>
        </section>
      ) : (
        <PlayerAiDecisionStrip decisions={decisions} />
      )}
    </>
  );
}

export function latestAttempts(decisions: AiDecision[]): AiDecision[] {
  const latest = new Map<string, AiDecision>();
  for (const item of decisions) {
    const key = `${item.provider}\u0000${item.model}`;
    const current = latest.get(key);
    if (!current || parseTime(item.request_started_at) >= parseTime(current.request_started_at)) {
      latest.set(key, item);
    }
  }
  return [...latest.values()].sort(
    (a, b) => a.provider.localeCompare(b.provider) || a.model.localeCompare(b.model)
  );
}

function parseTime(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
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
