import React, { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchAiEventQuality,
  fetchAiLeaderboard,
  fetchAiPositionAudit,
  type AiEventBreakdown,
  type AiEventQualityExperiment,
  type AiExperimentIdentity,
  type AiLeaderboardExperiment,
  type AiPositionAudit,
  type AiQualityPolicy
} from "../performanceApi";
import { useI18n } from "../i18n";
import { predictionPolicyLabel } from "../utils/predictionCopy";
import { UiIcon } from "./VisualIdentity";
import "./ai-performance.css";

const IntelligenceChart = lazy(() => import("../Chart"));

export function AiPerformancePage() {
  const { locale } = useI18n();
  const [selectedExperimentKey, setSelectedExperimentKey] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [expandedPositionId, setExpandedPositionId] = useState<string | null>(null);

  const leaderboard = useQuery({
    queryKey: ["ai-performance", "leaderboard"],
    queryFn: fetchAiLeaderboard,
    staleTime: 30_000,
    refetchInterval: 60_000
  });

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    const rows = leaderboard.data?.experiments ?? [];
    if (!query) return rows;
    return rows.filter((row) => {
      const identity = row.experiment;
      return `${identity.provider} ${identity.model} ${identity.prompt_version} ${identity.decision_policy_version} ${identity.execution_config_version}`
        .toLocaleLowerCase()
        .includes(query);
    });
  }, [leaderboard.data?.experiments, search]);

  const selectedExperiment = useMemo(() => {
    if (filtered.length === 0) return null;
    return (
      filtered.find((row) => identityKey(row.experiment) === selectedExperimentKey) ??
      filtered[0]
    );
  }, [filtered, selectedExperimentKey]);

  useEffect(() => {
    if (!selectedExperiment) return;
    const key = identityKey(selectedExperiment.experiment);
    if (selectedExperimentKey !== key) setSelectedExperimentKey(key);
    if (
      !selectedEventId ||
      !selectedExperiment.events.some((event) => event.canonical_event_id === selectedEventId)
    ) {
      setSelectedEventId(selectedExperiment.events.at(-1)?.canonical_event_id ?? null);
    }
  }, [selectedEventId, selectedExperiment, selectedExperimentKey]);

  const eventQuality = useQuery({
    queryKey: ["ai-performance", "event", selectedEventId],
    queryFn: () => fetchAiEventQuality(selectedEventId!),
    enabled: Boolean(selectedEventId),
    staleTime: 30_000,
    refetchInterval: 60_000
  });

  const selectedEventExperiment = useMemo(() => {
    if (!selectedExperiment || !eventQuality.data) return null;
    return (
      eventQuality.data.experiments.find((item) =>
        sameIdentity(item.experiment, selectedExperiment.experiment)
      ) ?? null
    );
  }, [eventQuality.data, selectedExperiment]);

  const positions = useQuery({
    queryKey: [
      "ai-performance",
      "positions",
      selectedEventId,
      selectedEventExperiment?.portfolio.account_id
    ],
    queryFn: () =>
      fetchAiPositionAudit(selectedEventId!, selectedEventExperiment!.portfolio.account_id),
    enabled: Boolean(selectedEventId && selectedEventExperiment?.portfolio.account_id),
    staleTime: 30_000
  });

  const selectedEvent = selectedExperiment?.events.find(
    (event) => event.canonical_event_id === selectedEventId
  );

  const refresh = () => {
    void leaderboard.refetch();
    if (selectedEventId) void eventQuality.refetch();
    if (positions.isEnabled) void positions.refetch();
  };

  return (
    <div className="performance-page">
      <div className="performance-main">
        <section className="performance-intro">
          <div>
            <span className="performance-kicker">{locale === "zh-CN" ? "AI 表现 / 预测积分" : "AI PERFORMANCE / PREDICTION POINTS"}</span>
            <h1>
              {locale === "zh-CN"
                ? "AI 表现榜"
                : "AI Performance"}
            </h1>
            <p>
              {locale === "zh-CN"
                ? "所有模型使用相同的初始预测积分和结算规则。积分只能用于比较预测表现，不可充值、提现、转让或兑换。"
                : "Every model uses the same initial prediction points and settlement rules. Points only compare prediction performance and cannot be purchased, withdrawn, transferred, or redeemed."}
            </p>
          </div>
          <div className="performance-intro-actions">
            <span className="performance-shadow-badge">POINTS ONLY</span>
            <a href="/review">{locale === "zh-CN" ? "查看复盘" : "Open review"}</a>
            <button type="button" onClick={refresh}>{locale === "zh-CN" ? "刷新" : "Refresh"}</button>
          </div>
        </section>

        {leaderboard.isLoading ? (
          <StateBlock text={locale === "zh-CN" ? "正在计算 AI 排行榜…" : "Loading AI leaderboard…"} />
        ) : leaderboard.error ? (
          <StateBlock error text={locale === "zh-CN" ? "AI 排行榜加载失败。" : "Failed to load AI leaderboard."} onRetry={() => void leaderboard.refetch()} />
        ) : (leaderboard.data?.experiments.length ?? 0) === 0 ? (
          <StateBlock text={locale === "zh-CN" ? "没有匹配的 AI experiment。" : "No matching AI experiments."} />
        ) : (
          <>
            {selectedExperiment && (
              <section className="performance-kpi-strip" aria-label={locale === "zh-CN" ? "AI 表现概览" : "AI performance overview"}>
                <PerformanceKpi icon="spark" label={locale === "zh-CN" ? "累计积分变化" : "Total points change"} value={signedMoney(selectedExperiment.realized_pnl, locale)} tone={tone(selectedExperiment.realized_pnl)} />
                <PerformanceKpi icon="trophy" label={locale === "zh-CN" ? "命中率" : "Hit rate"} value={rate(selectedExperiment.hit_rate, locale)} />
                <PerformanceKpi icon="layers" label={locale === "zh-CN" ? "最大积分回落" : "Max points decline"} value={rate(-selectedExperiment.worst_event_drawdown_pct, locale)} tone="negative" />
                <PerformanceKpi icon="clock" label={locale === "zh-CN" ? "已结算预测" : "Settled predictions"} value={`${selectedExperiment.bet_count}`} />
              </section>
            )}
            <section className="performance-overview-grid">
              <div className="performance-leaderboard-panel">
                <div className="performance-section-heading">
                  <div>
                    <span className="performance-kicker">LONG-RUN LEADERBOARD</span>
                    <h3>{locale === "zh-CN" ? "跨赛事积分排行" : "Cross-event points leaderboard"}</h3>
                  </div>
                  <input
                    aria-label={locale === "zh-CN" ? "搜索 AI" : "Search AI"}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder={locale === "zh-CN" ? "搜索模型 / Provider" : "Search model / provider"}
                  />
                </div>
                <p className="performance-ranking-note">
                  {rankingLabel(leaderboard.data?.ranking, locale)}
                </p>
                <div className="performance-leader-header" aria-hidden="true">
                  <span>{locale === "zh-CN" ? "排名" : "Rank"}</span>
                  <span>{locale === "zh-CN" ? "模型" : "Model"}</span>
                  <span className="performance-col-roi">{locale === "zh-CN" ? "积分变化率" : "Points rate"}</span>
                  <span className="performance-col-pnl">{locale === "zh-CN" ? "积分变化" : "Points change"}</span>
                  <span className="performance-col-dd">{locale === "zh-CN" ? "最大回落" : "Max decline"}</span>
                  <span className="performance-col-events">{locale === "zh-CN" ? "赛事" : "Events"}</span>
                </div>
                <div className="performance-leaderboard">
                  {filtered.map((row) => (
                    <LeaderboardRow
                      key={identityKey(row.experiment)}
                      row={row}
                      active={identityKey(row.experiment) === selectedExperimentKey}
                      locale={locale}
                      onSelect={() => {
                        setSelectedExperimentKey(identityKey(row.experiment));
                        setSelectedEventId(row.events.at(-1)?.canonical_event_id ?? null);
                        setExpandedPositionId(null);
                      }}
                    />
                  ))}
                  {filtered.length === 0 && (
                    <div className="performance-filter-empty">
                      {locale === "zh-CN"
                        ? "没有匹配的 AI 模型，请清空或修改搜索词。"
                        : "No AI models match. Clear or change the search query."}
                    </div>
                  )}
                </div>
              </div>

              {selectedExperiment && (
                <section className="performance-selected-summary" aria-label="Selected AI summary">
                  <div className="performance-selected-title">
                    <div>
                      <span className="performance-rank">#{selectedExperiment.rank}</span>
                      <h3>{providerLabel(selectedExperiment.experiment.provider)}</h3>
                      <small>{selectedExperiment.experiment.model}</small>
                    </div>
                    <PnlBadge value={selectedExperiment.realized_pnl} locale={locale} />
                  </div>
                  <div className="performance-summary-metrics">
                    <Metric label={locale === "zh-CN" ? "累计初始积分" : "Total initial points"} value={money(selectedExperiment.total_initial_bankroll, locale)} />
                    <Metric label={locale === "zh-CN" ? "当前积分" : "Current points"} value={money(selectedExperiment.equity, locale)} />
                    <Metric label={locale === "zh-CN" ? "积分变化率" : "Points change rate"} value={rate(selectedExperiment.realized_roi, locale)} tone={tone(selectedExperiment.realized_roi)} />
                    <Metric label={locale === "zh-CN" ? "最差赛事积分回落" : "Worst event points decline"} value={rate(-selectedExperiment.worst_event_drawdown_pct, locale)} tone="negative" />
                    <Metric label={locale === "zh-CN" ? "积分增加赛事" : "Points-positive events"} value={`${selectedExperiment.profitable_events}/${selectedExperiment.event_count}`} sub={rate(selectedExperiment.profitable_event_rate, locale)} />
                    <Metric label={locale === "zh-CN" ? "已结算预测 / 命中率" : "Settled predictions / hit rate"} value={`${selectedExperiment.bet_count}`} sub={rate(selectedExperiment.hit_rate, locale)} />
                  </div>
                  <div className="performance-version-line">
                    <span>{selectedExperiment.experiment.prompt_version}</span>
                    <span title={selectedExperiment.experiment.decision_policy_version}>{predictionPolicyLabel(selectedExperiment.experiment.decision_policy_version)}</span>
                    <span>{selectedExperiment.experiment.ai_view_version}</span>
                    <span title={selectedExperiment.experiment.execution_config_version}>
                      {executionConfigLabel(selectedExperiment.experiment.execution_config_version)}
                    </span>
                  </div>
                  <div className="performance-summary-guide">
                    <strong>{locale === "zh-CN" ? "如何理解榜单" : "How to read this leaderboard"}</strong>
                    <span>{locale === "zh-CN" ? "预测积分：所有模型使用统一初始积分。" : "Prediction points: every model starts with the same points."}</span>
                    <span>{locale === "zh-CN" ? "统一口径：同一快照、时间和结算规则。" : "Same basis: identical snapshots, timing and settlement rules."}</span>
                    <span>{locale === "zh-CN" ? "质量优先：积分变化需结合回落与样本量判断。" : "Quality first: read points change together with decline and sample size."}</span>
                  </div>
                </section>
              )}
            </section>

            {selectedExperiment && (
              <section className="performance-event-section">
                <div className="performance-section-heading">
                  <div>
                    <span className="performance-kicker">EVENT BREAKDOWN</span>
                    <h3>{locale === "zh-CN" ? "按赛事追踪预测积分" : "Trace prediction points by event"}</h3>
                  </div>
                  <span>{locale === "zh-CN" ? "点击赛事查看积分曲线、预测质量与逐轮记录" : "Select an event for points, prediction quality, and round-by-round records"}</span>
                </div>
                <div className="performance-event-list">
                  {selectedExperiment.events.map((event) => (
                    <EventButton
                      key={event.canonical_event_id}
                      event={event}
                      active={event.canonical_event_id === selectedEventId}
                      locale={locale}
                      onSelect={() => {
                        setSelectedEventId(event.canonical_event_id);
                        setExpandedPositionId(null);
                      }}
                    />
                  ))}
                </div>
              </section>
            )}

            {selectedEventId && selectedEvent && (
              <EventDetail
                locale={locale}
                event={selectedEvent}
                experiment={selectedEventExperiment}
                policy={eventQuality.data?.policy}
                loading={eventQuality.isLoading}
                error={Boolean(eventQuality.error)}
                onRetry={() => void eventQuality.refetch()}
                positions={positions.data?.positions ?? []}
                positionsLoading={positions.isLoading}
                positionsError={Boolean(positions.error)}
                onRetryPositions={() => void positions.refetch()}
                expandedPositionId={expandedPositionId}
                onTogglePosition={(id) => setExpandedPositionId((current) => (current === id ? null : id))}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function PerformanceKpi({
  icon,
  label,
  value,
  tone: toneClass
}: {
  icon: "clock" | "layers" | "spark" | "trophy";
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <article className="performance-kpi">
      <span className={`performance-kpi-icon is-${icon}`}><UiIcon name={icon} size={21} /></span>
      <div><span>{label}</span><strong className={toneClass}>{value}</strong></div>
    </article>
  );
}

function LeaderboardRow({
  row,
  active,
  locale,
  onSelect
}: {
  row: AiLeaderboardExperiment;
  active: boolean;
  locale: string;
  onSelect: () => void;
}) {
  return (
    <button className={`performance-leader-row ${active ? "active" : ""}`} type="button" onClick={onSelect}>
      <span className="performance-place">#{row.rank}</span>
      <span className="performance-model-name">
        <strong>{providerLabel(row.experiment.provider)}</strong>
        <small>{row.experiment.model} · {executionConfigLabel(row.experiment.execution_config_version)}</small>
      </span>
      <span className={`performance-table-number performance-col-roi ${tone(row.realized_roi)}`}>{rate(row.realized_roi, locale)}</span>
      <span className={`performance-table-number performance-col-pnl ${tone(row.realized_pnl)}`}>{signedMoney(row.realized_pnl, locale)}</span>
      <span className="performance-table-number performance-col-dd negative">{rate(-row.worst_event_drawdown_pct, locale)}</span>
      <span className="performance-table-number performance-col-events">{row.event_count}</span>
    </button>
  );
}

function EventButton({
  event,
  active,
  locale,
  onSelect
}: {
  event: AiEventBreakdown;
  active: boolean;
  locale: string;
  onSelect: () => void;
}) {
  return (
    <button className={`performance-event-btn ${active ? "active" : ""}`} type="button" onClick={onSelect}>
      <span className="performance-event-name">{event.event_name || shortId(event.canonical_event_id)}</span>
      <span>{formatDateRange(event.started_at, event.ended_at, locale)}</span>
      <strong className={tone(event.realized_pnl)}>{locale === "zh-CN" ? "积分变化" : "Points change"} {signedMoney(event.realized_pnl, locale)}</strong>
      <span className={tone(event.realized_roi)}>{locale === "zh-CN" ? "变化率" : "Change rate"} {rate(event.realized_roi, locale)}</span>
      <small>{locale === "zh-CN" ? "最大回落" : "Max decline"} {rate(-event.max_drawdown_pct, locale)}</small>
    </button>
  );
}

function EventDetail({
  locale,
  event,
  experiment,
  policy,
  loading,
  error,
  onRetry,
  positions,
  positionsLoading,
  positionsError,
  onRetryPositions,
  expandedPositionId,
  onTogglePosition
}: {
  locale: string;
  event: AiEventBreakdown;
  experiment: AiEventQualityExperiment | null;
  policy: AiQualityPolicy | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  positions: AiPositionAudit[];
  positionsLoading: boolean;
  positionsError: boolean;
  onRetryPositions: () => void;
  expandedPositionId: string | null;
  onTogglePosition: (id: string) => void;
}) {
  if (loading) return <StateBlock text={locale === "zh-CN" ? "正在读取赛事质量报告…" : "Loading event quality report…"} />;
  if (error) return <StateBlock error text={locale === "zh-CN" ? "赛事质量报告加载失败。" : "Failed to load event quality report."} onRetry={onRetry} />;
  if (!experiment || !policy) return <StateBlock text={locale === "zh-CN" ? "这个 AI 在该赛事还没有可评估的积分记录。" : "No evaluable points record for this AI in the event."} />;

  const portfolio = experiment.portfolio;
  const quality = experiment.quality;
  return (
    <section className="performance-detail">
      <div className="performance-detail-heading">
        <div>
          <span className="performance-kicker">EVENT DETAIL</span>
          <h3>{event.event_name || shortId(event.canonical_event_id)}</h3>
          <p>{formatDateRange(event.started_at, event.ended_at, locale)}</p>
        </div>
        <GateBadge status={experiment.gate.status} mode={experiment.gate.mode} locale={locale} />
      </div>

      <div className="performance-detail-metrics">
        <Metric label={locale === "zh-CN" ? "初始预测积分" : "Initial prediction points"} value={money(portfolio.initial_bankroll, locale)} />
        <Metric label={locale === "zh-CN" ? "当前积分" : "Current points"} value={money(portfolio.equity, locale)} />
        <Metric label={locale === "zh-CN" ? "已结算积分变化" : "Settled points change"} value={signedMoney(portfolio.realized_pnl, locale)} tone={tone(portfolio.realized_pnl)} />
        <Metric label={locale === "zh-CN" ? "积分变化率" : "Points change rate"} value={rate(portfolio.roi, locale)} tone={tone(portfolio.roi)} />
        <Metric label={locale === "zh-CN" ? "最大积分回落" : "Max points decline"} value={rate(-portfolio.max_drawdown_pct, locale)} tone="negative" />
        <Metric label={locale === "zh-CN" ? "正负积分比" : "Positive/negative points ratio"} value={decimal(portfolio.profit_factor, 2)} />
      </div>

      <div className="performance-two-column">
        <section className="performance-panel">
          <div className="performance-panel-heading">
            <div>
              <span className="performance-kicker">POINTS CURVE</span>
              <h4>{locale === "zh-CN" ? "赛事预测积分曲线" : "Event prediction-points curve"}</h4>
            </div>
            <span>{portfolio.wins}W · {portfolio.losses}L · {portfolio.rejected_bet_count} {locale === "zh-CN" ? "次未计分" : "not scored"}</span>
          </div>
          <div className="performance-chart-wrap">
            {experiment.equity_curve.length > 1 ? (
              <Suspense fallback={<div className="performance-chart-loading">Chart…</div>}>
                <IntelligenceChart option={equityChartOption(experiment, locale)} />
              </Suspense>
            ) : (
              <div className="performance-empty-inline">{locale === "zh-CN" ? "等待更多积分记录。" : "Waiting for more points records."}</div>
            )}
          </div>
        </section>

        <section className="performance-panel">
          <div className="performance-panel-heading">
            <div>
              <span className="performance-kicker">QUALITY GATE</span>
              <h4>{locale === "zh-CN" ? "为什么是这个结论" : "Why this gate status"}</h4>
            </div>
            <span>POINTS ONLY</span>
          </div>
          <div className="performance-gate-progress">
            <SampleProgress label={locale === "zh-CN" ? "已结算 Maps" : "Settled maps"} current={quality.settled_maps} target={policy.min_settled_maps} />
            <SampleProgress label={locale === "zh-CN" ? "已结算预测" : "Settled predictions"} current={portfolio.bet_count} target={policy.min_settled_bets} />
            <SampleProgress label={locale === "zh-CN" ? "独立预测样本" : "Prediction samples"} current={quality.prediction_sample_count} target={policy.min_prediction_samples} />
            <SampleProgress label="CLV" current={quality.clv_sample_count} target={policy.min_clv_samples} />
            <SampleProgress label={locale === "zh-CN" ? "市场对照" : "Market comparison"} current={quality.market_comparison.sample_count} target={policy.min_market_comparison_samples} />
          </div>
          {experiment.gate.failures.length > 0 && (
            <div className="performance-gate-reasons">
              {experiment.gate.failures.map((failure) => <span key={failure}>{failureLabel(failure, locale)}</span>)}
            </div>
          )}
        </section>
      </div>

      <div className="performance-three-column">
        <section className="performance-panel compact">
          <span className="performance-kicker">PREDICTION QUALITY</span>
          <h4>{locale === "zh-CN" ? "预测质量" : "Prediction quality"}</h4>
          <MetricLine label="AI Brier" value={decimal(quality.market_comparison.ai_average_brier_score ?? quality.average_brier_score, 3)} />
          <MetricLine label={locale === "zh-CN" ? "市场 Brier" : "Market Brier"} value={decimal(quality.market_comparison.market_average_brier_score, 3)} />
          <MetricLine label={locale === "zh-CN" ? "Brier 改善 vs 市场" : "Brier improvement vs market"} value={signedDecimal(quality.market_comparison.brier_improvement_vs_market, 3)} tone={tone(quality.market_comparison.brier_improvement_vs_market)} />
          <MetricLine label="Log Loss" value={decimal(quality.average_log_loss, 3)} />
          <MetricLine label="CLV" value={rate(quality.average_clv, locale)} tone={tone(quality.average_clv)} />
          <MetricLine label={locale === "zh-CN" ? "平均积分使用率" : "Average points usage"} value={rate(quality.average_stake_pct_of_available_cash, locale)} />
          <MetricLine label={locale === "zh-CN" ? "最长连续未命中" : "Longest miss streak"} value={`${quality.longest_losing_streak}`} />
          <p className="performance-method-note">
            {locale === "zh-CN"
              ? "Brier 越低越好；“改善 vs 市场” = 市场 Brier − AI Brier，正数表示 AI 更好。"
              : "Lower Brier is better. Improvement vs market = market Brier − AI Brier, so positive values favor the AI."}
          </p>
        </section>

        <section className="performance-panel compact performance-latency-panel">
          <span className="performance-kicker">EDGE AFTER AI RESPONSE</span>
          <h4>{locale === "zh-CN" ? "AI 给出答案后，纸面优势还剩多少？" : "How much paper edge remains after the AI responds?"}</h4>
          <div className="performance-latency-grid">
            {Object.entries(experiment.execution_latency.horizons).map(([horizon, row]) => (
              <div key={horizon} className="performance-latency-cell">
                <strong>T+{horizon}s</strong>
                <span>{locale === "zh-CN" ? "纸面 Edge 保留率" : "Paper edge retained"} {rate(row.actionable_rate, locale)}</span>
                <span>{locale === "zh-CN" ? "赔率变化" : "Odds move"} {rate(row.average_odds_slippage_pct, locale)}</span>
                <small>n={row.sample_count}</small>
              </div>
            ))}
            {Object.keys(experiment.execution_latency.horizons).length === 0 && (
              <div className="performance-empty-inline">{locale === "zh-CN" ? "暂无 AI 响应后的赔率样本。" : "No post-response market samples yet."}</div>
            )}
          </div>
          <p className="performance-method-note">
            {locale === "zh-CN"
              ? "只衡量 AI 响应后的市场观测中，仍满足模型 edge 条件的比例，用于比较预测与市场变化。AI 响应前的市场观测不计入。"
              : "Measures the share of post-response market observations where the model edge still qualifies, for comparing predictions with market movement. Pre-response observations are excluded."}
          </p>
        </section>

        <section className="performance-panel compact">
          <span className="performance-kicker">POINTS / ACTIVITY</span>
          <h4>{locale === "zh-CN" ? "积分与预测活动" : "Points and prediction activity"}</h4>
          <MetricLine label={locale === "zh-CN" ? "已结算预测" : "Settled predictions"} value={`${portfolio.bet_count}`} />
          <MetricLine label={locale === "zh-CN" ? "命中率" : "Hit rate"} value={rate(portfolio.hit_rate, locale)} />
          <MetricLine label={locale === "zh-CN" ? "累计预测积分" : "Total prediction points"} value={money(portfolio.turnover, locale)} />
          <MetricLine label={locale === "zh-CN" ? "最大单轮积分使用率" : "Largest round points usage"} value={rate(quality.largest_stake_pct_of_available_cash, locale)} />
          <MetricLine label={locale === "zh-CN" ? "待结算积分" : "Pending points"} value={money(portfolio.locked_balance, locale)} />
          <MetricLine label={locale === "zh-CN" ? "积分状态" : "Points status"} value={portfolio.status} />
        </section>
      </div>

      <section className="performance-panel performance-position-panel">
        <div className="performance-panel-heading">
          <div>
            <span className="performance-kicker">PREDICTION AUDIT</span>
            <h4>{locale === "zh-CN" ? "逐轮追溯：积分变化是怎么产生的" : "Prediction audit: where each points change came from"}</h4>
          </div>
          <span>{positions.length} {locale === "zh-CN" ? "轮预测" : "predictions"}</span>
        </div>
        {positionsLoading ? (
          <div className="performance-empty-inline">{locale === "zh-CN" ? "正在读取预测记录…" : "Loading prediction audit…"}</div>
        ) : positionsError ? (
          <button className="performance-retry" type="button" onClick={onRetryPositions}>{locale === "zh-CN" ? "预测记录加载失败 · 重试" : "Prediction audit failed · Retry"}</button>
        ) : positions.length === 0 ? (
          <div className="performance-empty-inline">{locale === "zh-CN" ? "这个赛事还没有已计分预测。" : "No scored predictions in this event yet."}</div>
        ) : (
          <div className="performance-position-list">
            {positions.map((position) => (
              <PositionRow
                key={position.id}
                position={position}
                locale={locale}
                expanded={position.id === expandedPositionId}
                onToggle={() => onTogglePosition(position.id)}
              />
            ))}
          </div>
        )}
      </section>
    </section>
  );
}

function PositionRow({
  position,
  locale,
  expanded,
  onToggle
}: {
  position: AiPositionAudit;
  locale: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={`performance-position ${expanded ? "expanded" : ""}`}>
      <button type="button" className="performance-position-main" onClick={onToggle} aria-expanded={expanded}>
        <span className="performance-position-map"><b>MAP {position.map_number ?? "?"}</b><small>{formatDateTime(position.opened_at, locale)}</small></span>
        <span className="performance-position-choice"><b>{position.selected_team?.name ?? predictionActionLabel(position.action, locale)}</b><small>{predictionActionLabel(position.action, locale)} · {locale === "zh-CN" ? "AI 预测" : "AI prediction"}</small></span>
        <span className="performance-position-stake"><b>{money(position.stake, locale)}</b><small>{locale === "zh-CN" ? "积分 · 倍率" : "points · multiplier"} {position.odds?.toFixed(3) ?? "—"}</small></span>
        <span className={`position-status status-${position.status.toLowerCase()}`}>{position.status}</span>
        <span className={`performance-position-pnl ${tone(position.realized_pnl)}`}><b>{position.realized_pnl == null ? "—" : signedMoney(position.realized_pnl, locale)}</b><small>{locale === "zh-CN" ? "积分变化" : "Points change"}</small></span>
        <span className="performance-position-action">{locale === "zh-CN" ? (expanded ? "收起" : "详情") : (expanded ? "Less" : "Details")} <b>{expanded ? "−" : "›"}</b></span>
      </button>
      {expanded && (
        <div className="performance-position-detail">
          <DetailDatum label={locale === "zh-CN" ? "预测前可用积分" : "Available points before"} value={money(position.cash_before, locale)} />
          <DetailDatum label={locale === "zh-CN" ? "结算后积分" : "Settled points"} value={position.payout == null ? "—" : money(position.payout, locale)} />
          <DetailDatum label={locale === "zh-CN" ? "未计分原因" : "Not-scored reason"} value={position.rejection_reason ?? "—"} />
          <DetailDatum label={locale === "zh-CN" ? "结算时间" : "Settled"} value={position.settled_at ? formatDateTime(position.settled_at, locale) : "—"} />
          <DetailDatum label="Map ID" value={shortId(position.canonical_map_id)} title={position.canonical_map_id} />
          <DetailDatum label="Decision ID" value={shortId(position.ai_decision_id)} title={position.ai_decision_id} />
        </div>
      )}
    </div>
  );
}

function SampleProgress({ label, current, target }: { label: string; current: number; target: number }) {
  const ratio = target > 0 ? Math.min(1, current / target) : 1;
  const complete = current >= target;
  return (
    <div className="performance-sample-progress">
      <div><span>{label}</span><strong className={complete ? "positive" : ""}>{current}/{target}</strong></div>
      <div className="performance-progress-track"><span style={{ width: `${ratio * 100}%` }} /></div>
    </div>
  );
}

function GateBadge({ status, mode, locale }: { status: string; mode: string; locale: string }) {
  const modeLabel = mode === "SHADOW_ONLY"
    ? (locale === "zh-CN" ? "仅积分" : "POINTS ONLY")
    : mode.replaceAll("_", " ");
  return <div className={`performance-gate-badge gate-${status.toLowerCase()}`}><strong>{status}</strong><span>{modeLabel}</span></div>;
}

function PnlBadge({ value, locale }: { value: number; locale: string }) {
  return <div className={`performance-pnl-badge ${tone(value)}`}><span>{locale === "zh-CN" ? "累计积分变化" : "Total points change"}</span><strong>{signedMoney(value, locale)}</strong></div>;
}

function Metric({ label, value, sub, tone: toneClass }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className="performance-metric"><span>{label}</span><strong className={toneClass}>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

function MetricLine({ label, value, tone: toneClass }: { label: string; value: string; tone?: string }) {
  return <div className="performance-metric-line"><span>{label}</span><strong className={toneClass}>{value}</strong></div>;
}

function DetailDatum({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div><span>{label}</span><strong title={title}>{value}</strong></div>;
}

function StateBlock({ text, error, onRetry }: { text: string; error?: boolean; onRetry?: () => void }) {
  return <section className={`performance-state ${error ? "error" : ""}`}><span>{text}</span>{onRetry && <button type="button" onClick={onRetry}>Retry</button>}</section>;
}

export function identityKey(identity: AiExperimentIdentity): string {
  return [identity.provider, identity.model, identity.prompt_version, identity.decision_policy_version, identity.ai_view_version, identity.execution_config_version].join("\u0000");
}

function sameIdentity(left: AiExperimentIdentity, right: AiExperimentIdentity): boolean {
  return identityKey(left) === identityKey(right);
}

function executionConfigLabel(value: string): string {
  return `cfg ${value.length > 24 ? `${value.slice(0, 22)}…` : value}`;
}

function rankingLabel(ranking: string | undefined, locale: string): string {
  if (ranking === "REALIZED_ROI_THEN_PNL") {
    return locale === "zh-CN"
      ? "排序规则：积分变化率从高到低；变化率相同时，再按累计积分变化从高到低。"
      : "Ranking: points change rate descending; ties are broken by total points change.";
  }
  return locale === "zh-CN" ? "排序规则由服务端排行榜定义。" : "Ranking follows the server leaderboard policy.";
}

function equityChartOption(experiment: AiEventQualityExperiment, locale: string): object {
  const points = experiment.equity_curve;
  return {
    animation: false,
    grid: { left: 55, right: 18, top: 18, bottom: 42 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value: number) => money(value, locale)
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: points.map((point) => formatChartTime(point.occurred_at, locale)),
      axisLabel: { color: "#728099", fontSize: 10 },
      axisLine: { lineStyle: { color: "rgba(255,255,255,.10)" } }
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: "#728099", fontSize: 10 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,.055)" } }
    },
    series: [
      {
        name: locale === "zh-CN" ? "积分余额" : "Points balance",
        type: "line",
        smooth: 0.22,
        showSymbol: points.length <= 18,
        symbolSize: 5,
        data: points.map((point) => point.equity),
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.08 }
      }
    ]
  };
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

function predictionActionLabel(value: string, locale: string): string {
  const labels: Record<string, [string, string]> = {
    BUY_A: ["PREDICT A", "预测 A"],
    BUY_B: ["PREDICT B", "预测 B"],
    NO_BUY: ["NO PREDICTION", "暂不预测"],
    INSUFFICIENT_DATA: ["INSUFFICIENT DATA", "数据不足"]
  };
  const normalized = value.trim().toUpperCase();
  const pair = labels[normalized] ?? [value.replaceAll("_", " "), value.replaceAll("_", " ")];
  return locale === "zh-CN" ? pair[1] : pair[0];
}

function failureLabel(value: string, locale: string): string {
  if (locale !== "zh-CN") return value.replaceAll("_", " ");
  const labels: Record<string, string> = {
    MIN_SETTLED_MAPS: "已结算地图样本不足",
    MIN_SETTLED_BETS: "已结算预测不足",
    MIN_PREDICTION_SAMPLES: "独立预测样本不足",
    MIN_CLV_SAMPLES: "CLV 样本不足",
    MIN_MARKET_COMPARISON_SAMPLES: "市场对照样本不足",
    ROI: "积分变化率未达标",
    CLV: "CLV 未达标",
    BRIER_VS_MARKET: "Brier 未优于市场",
    MAX_DRAWDOWN: "最大积分回落超阈值",
    BANKRUPTCY: "预测积分已耗尽"
  };
  return labels[value] ?? value;
}

function money(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
}

function signedMoney(value: number, locale: string): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${money(Math.abs(value), locale)}`;
}

function rate(value: number | null, locale: string): string {
  return value == null ? "—" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function decimal(value: number | null, digits: number): string {
  return value == null ? "—" : value.toFixed(digits);
}

function signedDecimal(value: number | null, digits: number): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`;
}

function tone(value: number | null): string {
  return value == null || value === 0 ? "" : value > 0 ? "positive" : "negative";
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function formatDateTime(value: string, locale: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : new Intl.DateTimeFormat(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}

function formatChartTime(value: string, locale: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : new Intl.DateTimeFormat(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}

function formatDateRange(start: string | null, end: string | null, locale: string): string {
  if (!start && !end) return locale === "zh-CN" ? "时间待确认" : "Date pending";
  const format = (value: string | null) => {
    if (!value) return "…";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat(locale, { year: "numeric", month: "2-digit", day: "2-digit" }).format(parsed);
  };
  return `${format(start)} → ${format(end)}`;
}
