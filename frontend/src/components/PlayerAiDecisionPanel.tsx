import React, { useEffect, useMemo, useState } from "react";
import type { AiDecision } from "../api";
import { useI18n } from "../i18n";
import { PlayerAiDecisionStrip } from "./PlayerAiDecisionStrip";

interface SnapshotDecisionPayload {
  decisions?: AiDecision[];
}

export function PlayerAiDecisionPanel({
  decisions,
  currentSnapshotId
}: {
  decisions: AiDecision[];
  currentSnapshotId?: string | null;
}) {
  const { locale } = useI18n();
  const [attempts, setAttempts] = useState<AiDecision[]>([]);

  useEffect(() => {
    let cancelled = false;
    if (!currentSnapshotId) {
      setAttempts([]);
      return () => { cancelled = true; };
    }

    void fetch(`/api/snapshots/${currentSnapshotId}`, {
      cache: "no-store",
      headers: { Accept: "application/json" }
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json() as Promise<SnapshotDecisionPayload>;
      })
      .then((payload) => {
        if (!cancelled) setAttempts(latestAttempts(payload.decisions ?? []));
      })
      .catch(() => {
        if (!cancelled) setAttempts([]);
      });

    return () => { cancelled = true; };
  }, [currentSnapshotId]);

  const latest = useMemo(() => latestAttempts(attempts), [attempts]);

  return (
    <>
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
      <PlayerAiDecisionStrip decisions={decisions} />
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
