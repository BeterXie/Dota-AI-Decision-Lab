import React, { useMemo, useState } from "react";
import type { AiBenchmarkExperiment, AiBenchmarkPayload, AiContextExperimentMetadata } from "../benchmarkApi";
import { predictionPolicyLabel } from "../utils/predictionCopy";
import "./baseline-benchmark.css";

export function BaselineBenchmarkPanel({
  data,
  loading,
  error,
  onRetry,
  locale
}: {
  data: AiBenchmarkPayload | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  locale: string;
}) {
  const [provider, setProvider] = useState<string>("ALL");
  const zh = locale === "zh-CN";
  const providers = useMemo(
    () => Array.from(new Set((data?.experiments ?? []).map((row) => row.experiment.provider))).sort(),
    [data?.experiments]
  );
  const rows = useMemo(
    () => (data?.experiments ?? []).filter((row) => provider === "ALL" || row.experiment.provider === provider),
    [data?.experiments, provider]
  );

  if (loading) {
    return <BenchmarkState text={zh ? "正在计算 AI 基线 Benchmark…" : "Calculating AI baseline benchmark…"} />;
  }
  if (error) {
    return (
      <BenchmarkState
        error
        text={zh ? "AI 基线 Benchmark 加载失败。" : "Failed to load AI baseline benchmark."}
        onRetry={onRetry}
      />
    );
  }
  if (!data) return null;

  const contract = data.baseline_contract;
  return (
    <section className="baseline-benchmark" aria-label={zh ? "AI 基线 Benchmark" : "AI baseline benchmark"}>
      <div className="performance-section-heading baseline-benchmark-heading">
        <div>
          <span className="performance-kicker">BASELINE CONTRACT · POINTS BENCHMARK</span>
          <h3>{zh ? "AI 基线 Benchmark" : "AI Baseline Benchmark"}</h3>
        </div>
        <span className="baseline-frozen-badge">{zh ? "已冻结" : "FROZEN"}</span>
      </div>

      <div className="baseline-contract-card">
        <div className="baseline-contract-title">
          <div>
            <strong>{contract.id}</strong>
            <span>{zh ? "后续 Prompt / Model / Policy / Context 变更都以此为参照" : "Future prompt, model, policy and context changes compare against this reference"}</span>
          </div>
          <code>{contract.frozen_at_commit.slice(0, 12)}</code>
        </div>
        <div className="baseline-contract-grid">
          <ContractField label="Prompt" value={contract.prompt_version} />
          <ContractField label={zh ? "预测策略" : "Prediction policy"} value={predictionPolicyLabel(contract.decision_policy_version)} title={contract.decision_policy_version} />
          <ContractField label={zh ? "AI Context / View" : "AI context / view"} value={contract.ai_view_version} />
          <ContractField label={zh ? "校准规则" : "Calibration policy"} value={data.methodology.calibration.version} />
        </div>
        <p>
          {zh
            ? "预测质量只取每张 Map 第一条可评估 forecast，避免重复 checkpoint 灌大样本；Context Test 会显示自己的受控实验参照，所有差值都只是描述性比较，不声称统计显著。"
            : "Forecast quality uses only the first evaluable forecast per map so repeated checkpoints cannot inflate N. Context tests show their controlled reference; all deltas are descriptive and do not claim statistical significance."}
        </p>
      </div>

      <div className="baseline-provider-filter" aria-label={zh ? "按 Provider 筛选" : "Filter by provider"}>
        <button type="button" className={provider === "ALL" ? "active" : ""} onClick={() => setProvider("ALL")}>
          {zh ? "全部" : "All"}
        </button>
        {providers.map((item) => (
          <button key={item} type="button" className={provider === item ? "active" : ""} onClick={() => setProvider(item)}>
            {item}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <BenchmarkState text={zh ? "当前还没有可评估的 AI experiment 数据。" : "No evaluable AI experiment data yet."} />
      ) : (
        <div className="baseline-experiment-list">
          {rows.map((row) => (
            <ExperimentCard key={identityKey(row)} row={row} locale={locale} />
          ))}
        </div>
      )}
    </section>
  );
}

function ExperimentCard({ row, locale }: { row: AiBenchmarkExperiment; locale: string }) {
  const zh = locale === "zh-CN";
  const baseline = row.baseline_role === "BASELINE";
  const context = row.context_experiment ?? null;
  const reference = context ? row.context_reference ?? null : row.baseline_reference;
  const delta = context ? row.delta_vs_context_reference ?? null : row.delta_vs_baseline;
  return (
    <article className={`baseline-experiment-card ${baseline ? "is-baseline" : "is-challenger"}`}>
      <header>
        <div>
          <span className={`baseline-role ${baseline ? "is-baseline" : "is-challenger"}`}>
            {baseline ? "BASELINE" : context ? "CONTEXT TEST" : "CHALLENGER"}
          </span>
          <strong>{row.experiment.provider} · {row.experiment.model}</strong>
          <small>
            {row.experiment.prompt_version} · <span title={row.experiment.decision_policy_version}>{predictionPolicyLabel(row.experiment.decision_policy_version)}</span> · {row.experiment.ai_view_version}
          </small>
          {context && (
            <small>
              {context.label}
              {contextDetail(context, zh)}
            </small>
          )}
        </div>
        {reference && (
          <span className="baseline-reference">
            {zh ? "参照" : "vs"} {reference.ai_view_version}
          </span>
        )}
      </header>

      <div className="baseline-metric-grid">
        <Metric label="N" value={String(row.samples.forecast_maps)} sub={`${row.samples.successful_decisions}/${row.samples.attempts} success`} />
        <Metric label={zh ? "预测准确率" : "Accuracy"} value={percent(row.quality.forecast_accuracy, locale)} />
        <Metric label="Brier" value={decimal(row.quality.average_brier_score)} />
        <Metric label="Log Loss" value={decimal(row.quality.average_log_loss)} />
        <Metric label="ECE" value={decimal(row.quality.calibration_error)} sub={zh ? "10 桶校准误差" : "10-bin calibration"} />
        <Metric label="CLV" value={signedPercent(row.quality.average_clv, locale)} sub={`N=${row.samples.clv_maps}`} />
        <Metric label={zh ? "Brier vs 市场" : "Brier vs market"} value={signedDecimal(row.quality.market_brier_improvement)} sub={`N=${row.samples.market_comparison_maps}`} />
        <Metric label={zh ? "弃权率" : "Abstention"} value={percent(row.quality.abstention_rate, locale)} />
        <Metric label={zh ? "平均延迟" : "Avg latency"} value={seconds(row.latency.average_seconds)} sub={`p95 ${seconds(row.latency.p95_seconds)}`} />
        <Metric label={zh ? "积分变化率" : "Points change rate"} value={signedPercent(row.portfolio.realized_roi, locale)} sub={`${row.portfolio.event_count} ${zh ? "赛事" : "events"}`} />
        <Metric label={zh ? "最差回撤" : "Worst DD"} value={signedPercent(row.portfolio.worst_event_drawdown_pct === null ? null : -row.portfolio.worst_event_drawdown_pct, locale)} />
        <Metric label={zh ? "Parse 成功率" : "Parse success"} value={percent(row.samples.parse_success_rate, locale)} />
      </div>

      {!baseline && delta && (
        <div className="baseline-delta-strip">
          <span>
            {context
              ? `${zh ? "相对实验参照" : "Improvement vs context reference"} · ${reference?.ai_view_version ?? context.reference_ai_view_version}`
              : zh
                ? "相对基线改善"
                : "Improvement vs baseline"}
          </span>
          <Delta label={zh ? "准确率" : "Accuracy"} value={signedPercent(delta.forecast_accuracy, locale)} />
          <Delta label="Brier" value={signedDecimal(delta.brier_improvement)} />
          <Delta label="Log Loss" value={signedDecimal(delta.log_loss_improvement)} />
          <Delta label="ECE" value={signedDecimal(delta.calibration_improvement)} />
          <Delta label="CLV" value={signedPercent(delta.clv_improvement, locale)} />
          <Delta label={zh ? "平均延迟" : "Avg latency"} value={signedSeconds(delta.average_latency_improvement_seconds)} />
          <Delta label={zh ? "积分变化率" : "Points change rate"} value={signedPercent(delta.shadow_roi_delta, locale)} />
        </div>
      )}
    </article>
  );
}

function contextDetail(context: AiContextExperimentMetadata, zh: boolean): string {
  if (context.removed_evidence.length > 0) {
    return ` · ${zh ? "移除" : "removed"}: ${context.removed_evidence.join(", ")}`;
  }
  if (context.schema_aligned_history) {
    return ` · ${zh ? "修正历史字段投影" : "history projection aligned"}`;
  }
  return ` · ${zh ? "匹配回放生产视图控制" : "matched replay production-view control"}`;
}

function ContractField({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div><span>{label}</span><code title={title}>{value}</code></div>;
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="baseline-metric"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

function Delta({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function BenchmarkState({ text, error, onRetry }: { text: string; error?: boolean; onRetry?: () => void }) {
  return (
    <div className={`baseline-benchmark-state ${error ? "is-error" : ""}`} role="status">
      <span>{text}</span>
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </div>
  );
}

function identityKey(row: AiBenchmarkExperiment): string {
  const item = row.experiment;
  return [item.provider, item.model, item.prompt_version, item.decision_policy_version, item.ai_view_version].join("|");
}

function percent(value: number | null, locale: string): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(locale === "zh-CN" ? "zh-CN" : "en-US", { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function signedPercent(value: number | null, locale: string): string {
  if (value === null) return "—";
  const formatted = percent(Math.abs(value), locale);
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatted}`;
}

function decimal(value: number | null): string {
  return value === null ? "—" : value.toFixed(3);
}

function signedDecimal(value: number | null): string {
  if (value === null) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(3)}`;
}

function seconds(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}s`;
}

function signedSeconds(value: number | null): string {
  if (value === null) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}s`;
}
