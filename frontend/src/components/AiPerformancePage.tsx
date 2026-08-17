import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useI18n, type Locale } from "../i18n";
import {
  fetchAiPerformance,
  type PerformanceDecision,
  type PerformanceExperiment
} from "../performanceApi";
import "./AiPerformancePage.css";

type SortMetric = "unit_roi" | "average_brier" | "buy_accuracy" | "success_rate" | "average_latency_seconds";
type StatusFilter = "ALL" | "SUCCESS" | "FAILED";

const copy = {
  "zh-CN": {
    back: "← 实时比赛",
    review: "赛后复盘",
    title: "AI Performance",
    kicker: "MODEL & EXPERIMENT INTELLIGENCE",
    headline: "别只问 AI 猜对了几次，要知道是哪一版、靠什么、花多久、能不能复现。",
    description: "按模型、Prompt、决策策略和 AI View 版本拆开比较；每条结果都能追到 immutable snapshot、AI input hash、延迟链路与结算证据。",
    audit: "可审计 · 无赛后回填",
    refresh: "刷新",
    attempts: "AI 调用",
    success: "成功解析",
    evaluated: "已结算/评估",
    buyAccuracy: "BUY 命中率",
    brier: "平均 Brier",
    unitRoi: "1-unit ROI",
    experiments: "实验版本",
    compareTitle: "实验对比",
    compareHint: "最多固定 3 个版本。Brier / Log loss 越低越好；ROI、命中率越高越好。",
    noCompare: "从下方实验表点“加入对比”，这里会并排展示。",
    identity: "实验身份",
    sample: "样本",
    reliability: "可靠性",
    probability: "概率质量",
    returns: "标准化收益",
    latency: "速度",
    tokens: "Token",
    versions: "版本",
    tableTitle: "版本成绩单",
    tableHint: "同一个模型升级 Prompt / Policy / AI View 后不会被混算。",
    sortBy: "排序",
    roiSort: "1-unit ROI",
    brierSort: "Brier（低优先）",
    accuracySort: "BUY 命中率",
    successSort: "解析成功率",
    latencySort: "模型延迟（低优先）",
    model: "模型",
    rounds: "调用 / 成功",
    buy: "BUY",
    pnl: "1-unit P&L",
    p95: "P95 延迟",
    cache: "输入缓存",
    compare: "加入对比",
    remove: "移出对比",
    ledgerTitle: "Decision Trace",
    ledgerHint: "点任意一条决策，打开完整审计链路。",
    search: "搜索队伍、模型、snapshot/hash…",
    allExperiments: "全部实验",
    allStatuses: "全部状态",
    successStatus: "成功",
    failedStatus: "失败",
    noRows: "当前筛选没有决策记录。",
    traceTitle: "决策审计链路",
    close: "关闭",
    match: "比赛",
    decision: "决策",
    evidence: "AI 依据",
    evaluation: "赛后评估",
    timing: "延迟链路",
    tokenUsage: "Token 使用",
    auditIdentity: "可复现身份",
    snapshot: "Snapshot",
    inputHash: "AI Input Hash",
    providerRequest: "模型请求",
    endToEnd: "端到端",
    queue: "排队",
    prepare: "输入准备",
    reasonNone: "没有结构化理由",
    blockerNone: "没有 blocker",
    loading: "正在读取 AI 实验记录…",
    proError: "无法读取 AI Performance。请确认当前账号拥有全局 Pro 权限。",
    methodology: "口径",
    latest: "最近决策"
  },
  en: {
    back: "← Live matches",
    review: "Post-match review",
    title: "AI Performance",
    kicker: "MODEL & EXPERIMENT INTELLIGENCE",
    headline: "Don’t stop at how often AI was right. Know which version, why, how fast, and whether it can be reproduced.",
    description: "Compare model, prompt, policy and AI-view versions separately. Every result traces back to an immutable snapshot, AI input hash, latency path and settlement evidence.",
    audit: "Auditable · no hindsight refill",
    refresh: "Refresh",
    attempts: "AI calls",
    success: "Parsed successfully",
    evaluated: "Evaluated",
    buyAccuracy: "BUY accuracy",
    brier: "Average Brier",
    unitRoi: "1-unit ROI",
    experiments: "Experiment versions",
    compareTitle: "Experiment comparison",
    compareHint: "Pin up to 3 versions. Lower Brier / log loss is better; higher ROI and accuracy are better.",
    noCompare: "Choose “Compare” in the experiment table to pin versions here.",
    identity: "Experiment identity",
    sample: "Sample",
    reliability: "Reliability",
    probability: "Probability quality",
    returns: "Standardized return",
    latency: "Speed",
    tokens: "Tokens",
    versions: "Versions",
    tableTitle: "Version scoreboard",
    tableHint: "Prompt / policy / AI-view upgrades are never silently merged into older results.",
    sortBy: "Sort",
    roiSort: "1-unit ROI",
    brierSort: "Brier (low first)",
    accuracySort: "BUY accuracy",
    successSort: "Parse success",
    latencySort: "Model latency (low first)",
    model: "Model",
    rounds: "Calls / success",
    buy: "BUY",
    pnl: "1-unit P&L",
    p95: "P95 latency",
    cache: "Input cache",
    compare: "Compare",
    remove: "Unpin",
    ledgerTitle: "Decision Trace",
    ledgerHint: "Open any decision to inspect the full audit chain.",
    search: "Search teams, model, snapshot/hash…",
    allExperiments: "All experiments",
    allStatuses: "All statuses",
    successStatus: "Success",
    failedStatus: "Failed",
    noRows: "No decisions match the current filters.",
    traceTitle: "Decision audit trail",
    close: "Close",
    match: "Match",
    decision: "Decision",
    evidence: "AI evidence",
    evaluation: "Post-match evaluation",
    timing: "Latency path",
    tokenUsage: "Token usage",
    auditIdentity: "Reproducible identity",
    snapshot: "Snapshot",
    inputHash: "AI Input Hash",
    providerRequest: "Provider request",
    endToEnd: "End-to-end",
    queue: "Queue",
    prepare: "Input prep",
    reasonNone: "No structured reasons",
    blockerNone: "No blockers",
    loading: "Loading AI experiment records…",
    proError: "AI Performance could not be loaded. Confirm this account has global Pro access.",
    methodology: "Methodology",
    latest: "Latest decision"
  }
} as const;

export function AiPerformancePage() {
  const { locale, setLocale } = useI18n();
  const text = copy[locale];
  const [sortMetric, setSortMetric] = useState<SortMetric>("unit_roi");
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [experimentFilter, setExperimentFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [search, setSearch] = useState("");
  const [selectedDecision, setSelectedDecision] = useState<PerformanceDecision | null>(null);

  const performance = useQuery({
    queryKey: ["ai-performance"],
    queryFn: () => fetchAiPerformance(1000),
    staleTime: 30_000,
    refetchInterval: 60_000
  });

  const sortedExperiments = useMemo(
    () => sortExperiments(performance.data?.experiments ?? [], sortMetric),
    [performance.data?.experiments, sortMetric]
  );
  const compared = useMemo(
    () => compareIds.map((id) => performance.data?.experiments.find((item) => item.id === id)).filter(Boolean) as PerformanceExperiment[],
    [compareIds, performance.data?.experiments]
  );
  const decisions = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return (performance.data?.decisions ?? []).filter((item) => {
      if (experimentFilter !== "ALL" && item.experiment_id !== experimentFilter) return false;
      if (statusFilter === "SUCCESS" && item.parse_status !== "SUCCESS") return false;
      if (statusFilter === "FAILED" && item.parse_status === "SUCCESS") return false;
      if (!query) return true;
      const match = item.match;
      const haystack = [
        item.provider,
        item.model,
        item.model_version,
        item.prompt_version,
        item.decision_policy_version,
        item.ai_view_version,
        item.snapshot_id,
        item.snapshot_hash,
        item.ai_input_hash ?? "",
        match?.team_a?.name ?? "",
        match?.team_b?.name ?? "",
        match?.tournament_name ?? ""
      ].join(" ").toLocaleLowerCase();
      return haystack.includes(query);
    });
  }, [performance.data?.decisions, experimentFilter, statusFilter, search]);

  const toggleCompare = (id: string) => {
    setCompareIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length < 3) return [...current, id];
      return [...current.slice(1), id];
    });
  };

  return (
    <div className="perf-page">
      <header className="perf-header">
        <div className="perf-brand">
          <a href="/" className="perf-back">{text.back}</a>
          <div><span className="perf-kicker">DOTA AI DECISION LAB</span><h1>{text.title}</h1></div>
        </div>
        <div className="perf-header-actions">
          <a href="/review">{text.review}</a>
          <button className={locale === "zh-CN" ? "active" : ""} onClick={() => setLocale("zh-CN")}>中文</button>
          <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}>EN</button>
          <button onClick={() => void performance.refetch()}>{text.refresh}</button>
        </div>
      </header>

      <main className="perf-main">
        <section className="perf-hero">
          <div>
            <span className="perf-kicker">{text.kicker}</span>
            <h2>{text.headline}</h2>
            <p>{text.description}</p>
          </div>
          <div className="perf-audit-pill">✓ {text.audit}</div>
        </section>

        {performance.isLoading && <div className="perf-state">{text.loading}</div>}
        {performance.error && <div className="perf-state error">{text.proError}<small>{performance.error.message}</small></div>}

        {performance.data && (
          <>
            <SummaryCards locale={locale} text={text} summary={performance.data.summary} />

            <section className="perf-panel perf-compare-panel">
              <SectionHeading kicker="COMPARE" title={text.compareTitle} hint={text.compareHint} />
              {compared.length ? (
                <div className="perf-compare-grid">
                  {compared.map((item) => (
                    <CompareCard key={item.id} item={item} locale={locale} text={text} onRemove={() => toggleCompare(item.id)} />
                  ))}
                </div>
              ) : <div className="perf-empty compact">{text.noCompare}</div>}
            </section>

            <section className="perf-panel">
              <div className="perf-toolbar">
                <SectionHeading kicker="EXPERIMENTS" title={text.tableTitle} hint={text.tableHint} />
                <label className="perf-sort-label">
                  <span>{text.sortBy}</span>
                  <select value={sortMetric} onChange={(event) => setSortMetric(event.target.value as SortMetric)}>
                    <option value="unit_roi">{text.roiSort}</option>
                    <option value="average_brier">{text.brierSort}</option>
                    <option value="buy_accuracy">{text.accuracySort}</option>
                    <option value="success_rate">{text.successSort}</option>
                    <option value="average_latency_seconds">{text.latencySort}</option>
                  </select>
                </label>
              </div>
              <ExperimentTable
                experiments={sortedExperiments}
                compareIds={compareIds}
                onCompare={toggleCompare}
                locale={locale}
                text={text}
              />
            </section>

            <section className="perf-panel">
              <div className="perf-toolbar perf-ledger-toolbar">
                <SectionHeading kicker="AUDIT LEDGER" title={text.ledgerTitle} hint={text.ledgerHint} />
                <div className="perf-filters">
                  <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={text.search} />
                  <select value={experimentFilter} onChange={(event) => setExperimentFilter(event.target.value)}>
                    <option value="ALL">{text.allExperiments}</option>
                    {performance.data.experiments.map((item) => (
                      <option key={item.id} value={item.id}>{providerLabel(item.provider)} · {shortModel(item.model)} · {item.prompt_version}</option>
                    ))}
                  </select>
                  <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
                    <option value="ALL">{text.allStatuses}</option>
                    <option value="SUCCESS">{text.successStatus}</option>
                    <option value="FAILED">{text.failedStatus}</option>
                  </select>
                </div>
              </div>
              <DecisionLedger decisions={decisions} locale={locale} text={text} onOpen={setSelectedDecision} />
            </section>

            <section className="perf-methodology">
              <span className="perf-kicker">{text.methodology.toUpperCase()}</span>
              <div>
                <code>{performance.data.methodology.experiment_identity.join(" + ")}</code>
                <span>· {performance.data.methodology.buy_accuracy}</span>
                <span>· {performance.data.methodology.unit_roi}</span>
                <span>· {performance.data.methodology.source}</span>
              </div>
            </section>
          </>
        )}
      </main>

      {selectedDecision && (
        <DecisionTraceDialog decision={selectedDecision} locale={locale} text={text} onClose={() => setSelectedDecision(null)} />
      )}
    </div>
  );
}

function SummaryCards({ locale, text, summary }: { locale: Locale; text: typeof copy[Locale]; summary: Awaited<ReturnType<typeof fetchAiPerformance>>["summary"] }) {
  return (
    <section className="perf-kpis">
      <Kpi label={text.attempts} value={`${summary.attempts}`} sub={`${summary.experiment_count} ${text.experiments}`} />
      <Kpi label={text.success} value={percent(summary.success_rate, locale)} sub={`${summary.successful}/${summary.attempts}`} />
      <Kpi label={text.evaluated} value={`${summary.evaluated}`} sub={`BUY ${summary.settled_buy_decisions}`} />
      <Kpi label={text.buyAccuracy} value={percent(summary.buy_accuracy, locale)} sub={`${summary.correct_buy_decisions}/${summary.settled_buy_decisions}`} />
      <Kpi label={text.brier} value={decimal(summary.average_brier, 3)} sub="↓ better" />
      <Kpi label={text.unitRoi} value={percent(summary.unit_roi, locale)} sub={`${signed(summary.unit_pnl, 2)} / ${summary.unit_bets}`} tone={tone(summary.unit_roi)} />
    </section>
  );
}

function Kpi({ label, value, sub, tone: toneClass }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className="perf-kpi"><span>{label}</span><strong className={toneClass}>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

function SectionHeading({ kicker, title, hint }: { kicker: string; title: string; hint: string }) {
  return <div className="perf-section-heading"><div><span className="perf-kicker">{kicker}</span><h3>{title}</h3></div><p>{hint}</p></div>;
}

function CompareCard({ item, locale, text, onRemove }: { item: PerformanceExperiment; locale: Locale; text: typeof copy[Locale]; onRemove: () => void }) {
  return (
    <article className="perf-compare-card">
      <div className="perf-compare-head">
        <div><strong>{providerLabel(item.provider)}</strong><span>{item.model}</span></div>
        <button onClick={onRemove}>{text.remove}</button>
      </div>
      <VersionStack item={item} />
      <div className="perf-compare-metrics">
        <MiniMetric label={text.sample} value={`${item.successful}/${item.attempts}`} />
        <MiniMetric label={text.buyAccuracy} value={percent(item.buy_accuracy, locale)} />
        <MiniMetric label="Brier ↓" value={decimal(item.average_brier, 3)} />
        <MiniMetric label="Log loss ↓" value={decimal(item.average_log_loss, 3)} />
        <MiniMetric label={text.unitRoi} value={percent(item.unit_roi, locale)} tone={tone(item.unit_roi)} />
        <MiniMetric label={text.pnl} value={signed(item.unit_pnl, 2)} tone={tone(item.unit_pnl)} />
        <MiniMetric label="Avg latency" value={seconds(item.average_latency_seconds)} />
        <MiniMetric label={text.p95} value={seconds(item.p95_latency_seconds)} />
      </div>
    </article>
  );
}

function ExperimentTable({ experiments, compareIds, onCompare, locale, text }: { experiments: PerformanceExperiment[]; compareIds: string[]; onCompare: (id: string) => void; locale: Locale; text: typeof copy[Locale] }) {
  return (
    <div className="perf-table-wrap">
      <table className="perf-table">
        <thead><tr><th>{text.model}</th><th>{text.versions}</th><th>{text.rounds}</th><th>{text.buyAccuracy}</th><th>Brier ↓</th><th>{text.unitRoi}</th><th>{text.pnl}</th><th>{text.p95}</th><th>{text.cache}</th><th /></tr></thead>
        <tbody>
          {experiments.map((item) => {
            const pinned = compareIds.includes(item.id);
            return (
              <tr key={item.id} className={pinned ? "pinned" : ""}>
                <td><strong>{providerLabel(item.provider)}</strong><span>{item.model}</span></td>
                <td><VersionStack item={item} compact /></td>
                <td><strong>{item.attempts}</strong><span>{item.successful} ✓ · {item.failed} ✕</span></td>
                <td><strong>{percent(item.buy_accuracy, locale)}</strong><span>{item.correct_buy_decisions}/{item.settled_buy_decisions}</span></td>
                <td><strong>{decimal(item.average_brier, 3)}</strong><span>log {decimal(item.average_log_loss, 3)}</span></td>
                <td><strong className={tone(item.unit_roi)}>{percent(item.unit_roi, locale)}</strong><span>{item.unit_bets} bets</span></td>
                <td><strong className={tone(item.unit_pnl)}>{signed(item.unit_pnl, 2)}</strong></td>
                <td><strong>{seconds(item.p95_latency_seconds)}</strong><span>avg {seconds(item.average_latency_seconds)}</span></td>
                <td><strong>{percent(item.cached_input_ratio, locale)}</strong><span>{item.average_total_tokens == null ? "—" : `${Math.round(item.average_total_tokens)} tok`}</span></td>
                <td><button className={pinned ? "active" : ""} onClick={() => onCompare(item.id)}>{pinned ? text.remove : text.compare}</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {experiments.length === 0 && <div className="perf-empty">—</div>}
    </div>
  );
}

function DecisionLedger({ decisions, locale, text, onOpen }: { decisions: PerformanceDecision[]; locale: Locale; text: typeof copy[Locale]; onOpen: (decision: PerformanceDecision) => void }) {
  return (
    <div className="perf-decision-list">
      {decisions.map((item) => {
        const match = item.match;
        const teams = match?.team_a && match?.team_b ? `${match.team_a.name} vs ${match.team_b.name}` : item.canonical_map_id ?? "—";
        return (
          <button className="perf-decision-row" key={item.id} onClick={() => onOpen(item)}>
            <div className="perf-decision-match"><strong>{teams}</strong><span>{formatDate(item.decision_at, locale)}{match?.map_number != null ? ` · MAP ${match.map_number}` : ""}</span></div>
            <div className="perf-decision-model"><strong>{providerLabel(item.provider)}</strong><span>{shortModel(item.model)} · {item.prompt_version}</span></div>
            <ActionBadge action={item.action} status={item.parse_status} />
            <div className="perf-decision-score"><strong>{item.evaluation?.result_correct == null ? "—" : item.evaluation.result_correct ? "✓" : "✕"}</strong><span>Brier {decimal(item.evaluation?.brier_score ?? null, 3)}</span></div>
            <div className="perf-decision-score"><strong className={tone(item.evaluation?.unit_pnl ?? null)}>{signed(item.evaluation?.unit_pnl ?? null, 2)}</strong><span>1-unit</span></div>
            <div className="perf-decision-hash"><code>{shortHash(item.snapshot_hash)}</code><span>{shortHash(item.ai_input_hash)}</span></div>
            <span className="perf-open-arrow">›</span>
          </button>
        );
      })}
      {decisions.length === 0 && <div className="perf-empty">{text.noRows}</div>}
    </div>
  );
}

function DecisionTraceDialog({ decision, locale, text, onClose }: { decision: PerformanceDecision; locale: Locale; text: typeof copy[Locale]; onClose: () => void }) {
  const match = decision.match;
  return (
    <div className="perf-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="perf-dialog" role="dialog" aria-modal="true" aria-label={text.traceTitle}>
        <header className="perf-dialog-header">
          <div><span className="perf-kicker">AUDIT TRACE</span><h2>{text.traceTitle}</h2></div>
          <button onClick={onClose}>{text.close}</button>
        </header>
        <div className="perf-dialog-body">
          <TraceSection title={text.match}>
            <div className="perf-trace-hero"><strong>{match?.team_a?.name ?? "Team A"} <span>vs</span> {match?.team_b?.name ?? "Team B"}</strong><small>{match?.tournament_name ?? "—"}{match?.map_number != null ? ` · MAP ${match.map_number}` : ""} · {formatDate(decision.decision_at, locale)}</small></div>
          </TraceSection>

          <TraceSection title={text.decision}>
            <div className="perf-detail-grid">
              <Detail label="Provider / model" value={`${decision.provider} / ${decision.model}`} />
              <Detail label="Action" value={decision.action ?? decision.parse_status} />
              <Detail label="Fair p(A)" value={percent(decision.fair_probability_a, locale)} />
              <Detail label="Confidence" value={percent(decision.confidence, locale)} />
              <Detail label="Market" value={decision.market_assessment ?? "—"} />
              <Detail label="Stake / bankroll" value={`${decimal(decision.stake, 2)} / ${decimal(decision.bankroll_before, 2)}`} />
            </div>
            {decision.error && <div className="perf-error-callout">{decision.error}</div>}
          </TraceSection>

          <TraceSection title={text.evidence}>
            <div className="perf-evidence-columns">
              <div><span className="perf-detail-label">Primary reasons</span><ul>{decision.primary_reasons.length ? decision.primary_reasons.map((item, index) => <li key={`${index}:${item}`}>{item}</li>) : <li className="muted">{text.reasonNone}</li>}</ul></div>
              <div><span className="perf-detail-label">Blockers</span><ul>{decision.blockers.length ? decision.blockers.map((item, index) => <li key={`${index}:${item}`}>{item}</li>) : <li className="muted">{text.blockerNone}</li>}</ul></div>
            </div>
          </TraceSection>

          <TraceSection title={text.evaluation}>
            {decision.evaluation ? (
              <div className="perf-detail-grid">
                <Detail label="Result" value={decision.evaluation.result_correct == null ? "—" : decision.evaluation.result_correct ? "✓ CORRECT" : "✕ WRONG"} />
                <Detail label="Brier" value={decimal(decision.evaluation.brier_score, 4)} />
                <Detail label="Log loss" value={decimal(decision.evaluation.log_loss, 4)} />
                <Detail label="CLV" value={decimal(decision.evaluation.clv, 4)} />
                <Detail label="1-unit P&L" value={signed(decision.evaluation.unit_pnl, 3)} />
                <Detail label="Virtual P&L" value={signed(decision.evaluation.virtual_pnl, 2)} />
                <Detail label="Metrics version" value={decision.evaluation.metrics_version} />
                <Detail label="Evaluated" value={formatDate(decision.evaluation.evaluated_at, locale)} />
              </div>
            ) : <span className="perf-muted">—</span>}
          </TraceSection>

          <TraceSection title={text.auditIdentity}>
            <div className="perf-hash-stack">
              <HashRow label="Snapshot ID" value={decision.snapshot_id} />
              <HashRow label="Snapshot hash" value={decision.snapshot_hash} />
              <HashRow label={text.inputHash} value={decision.ai_input_hash ?? "—"} />
              <HashRow label="Model version" value={decision.model_version} />
              <HashRow label="Prompt version" value={decision.prompt_version} />
              <HashRow label="Decision policy" value={decision.decision_policy_version} />
              <HashRow label="AI view" value={decision.ai_view_version} />
            </div>
          </TraceSection>

          <TraceSection title={text.timing}>
            <div className="perf-timing-flow">
              <Timing label={text.queue} value={decision.trace.queue_seconds} />
              <span>→</span>
              <Timing label={text.prepare} value={decision.trace.input_prepare_seconds} />
              <span>→</span>
              <Timing label={text.providerRequest} value={decision.trace.provider_latency_seconds} />
              <span>→</span>
              <Timing label={text.endToEnd} value={decision.trace.end_to_end_seconds} strong />
            </div>
          </TraceSection>

          <TraceSection title={text.tokenUsage}>
            <div className="perf-detail-grid token-grid">
              <Detail label="Input" value={integer(decision.tokens.input)} />
              <Detail label="Cached input" value={integer(decision.tokens.cached_input)} />
              <Detail label="Reasoning" value={integer(decision.tokens.reasoning)} />
              <Detail label="Output" value={integer(decision.tokens.output)} />
              <Detail label="Total" value={integer(decision.tokens.total)} />
            </div>
          </TraceSection>
        </div>
      </section>
    </div>
  );
}

function TraceSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="perf-trace-section"><h3>{title}</h3>{children}</section>;
}
function Detail({ label, value }: { label: string; value: string }) {
  return <div className="perf-detail"><span>{label}</span><strong>{value}</strong></div>;
}
function HashRow({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><code>{value}</code></div>;
}
function Timing({ label, value, strong = false }: { label: string; value: number | null; strong?: boolean }) {
  return <div className={strong ? "strong" : ""}><span>{label}</span><strong>{seconds(value)}</strong></div>;
}
function MiniMetric({ label, value, tone: toneClass }: { label: string; value: string; tone?: string }) {
  return <div><span>{label}</span><strong className={toneClass}>{value}</strong></div>;
}
function VersionStack({ item, compact = false }: { item: PerformanceExperiment; compact?: boolean }) {
  return <div className={compact ? "perf-version-stack compact" : "perf-version-stack"}><code>{item.prompt_version}</code><span>policy {item.decision_policy_version}</span><span>view {item.ai_view_version}</span><span>model {item.model_version}</span></div>;
}
function ActionBadge({ action, status }: { action: string | null; status: string }) {
  const failed = status !== "SUCCESS";
  const label = failed ? status : action ?? "NO DECISION";
  return <span className={`perf-action ${failed ? "failed" : action?.startsWith("BUY") ? "buy" : "neutral"}`}>{label.replaceAll("_", " ")}</span>;
}

function sortExperiments(items: PerformanceExperiment[], metric: SortMetric): PerformanceExperiment[] {
  const copyItems = [...items];
  const lowIsBetter = metric === "average_brier" || metric === "average_latency_seconds";
  copyItems.sort((a, b) => {
    const av = a[metric];
    const bv = b[metric];
    if (av == null && bv == null) return b.attempts - a.attempts;
    if (av == null) return 1;
    if (bv == null) return -1;
    return lowIsBetter ? av - bv : bv - av;
  });
  return copyItems;
}
function providerLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("local_openai")) return "Local GPT";
  if (normalized.includes("openai")) return "GPT";
  if (normalized.includes("anthropic")) return "Claude";
  if (normalized.includes("gemini") || normalized.includes("google")) return "Gemini";
  if (normalized.includes("deepseek")) return "DeepSeek";
  if (normalized.includes("kimi")) return "Kimi";
  return value;
}
function shortModel(value: string): string { return value.length > 26 ? `${value.slice(0, 23)}…` : value; }
function shortHash(value: string | null): string { return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "—"; }
function percent(value: number | null, locale: Locale): string { return value == null ? "—" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value); }
function decimal(value: number | null, digits: number): string { return value == null ? "—" : value.toFixed(digits); }
function signed(value: number | null, digits: number): string { return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(digits)}`; }
function integer(value: number | null): string { return value == null ? "—" : new Intl.NumberFormat().format(value); }
function seconds(value: number | null): string { return value == null ? "—" : value < 1 ? `${Math.round(value * 1000)}ms` : `${value.toFixed(value >= 10 ? 1 : 2)}s`; }
function tone(value: number | null): string { return value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : ""; }
function formatDate(value: string, locale: Locale): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(parsed);
}
