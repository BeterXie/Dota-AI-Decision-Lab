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
import "./ai-performance.css";

const IntelligenceChart = lazy(() => import("../Chart"));

export function AiPerformancePage() {
  const { locale, setLocale } = useI18n();
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
      return `${identity.provider} ${identity.model} ${identity.prompt_version} ${identity.decision_policy_version}`
        .toLocaleLowerCase()
        .includes(query);
    });
  }, [leaderboard.data?.experiments, search]);

  const selectedExperiment = useMemo(() => {
    const rows = leaderboard.data?.experiments ?? [];
    if (rows.length === 0) return null;
    return (
      rows.find((row) => identityKey(row.experiment) === selectedExperimentKey) ??
      filtered[0] ??
      rows[0]
    );
  }, [leaderboard.data?.experiments, filtered, selectedExperimentKey]);

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
      <header className="performance-header">
        <div className="performance-brand">
          <a href="/" className="performance-back">
            ← {locale === "zh-CN" ? "返回比赛" : "Back to matches"}
          </a>
          <div>
            <span className="performance-kicker">AI SHADOW COMPETITION</span>
            <h1>{locale === "zh-CN" ? "AI 盈利与质量" : "AI Performance"}</h1>
          </div>
        </div>
        <div className="performance-header-actions">
          <a href="/review">{locale === "zh-CN" ? "比赛复盘" : "Match review"}</a>
          <button className={locale === "zh-CN" ? "active" : ""} onClick={() => setLocale("zh-CN")}>
            中文
          </button>
          <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}>
            EN
          </button>
          <button onClick={refresh}>{locale === "zh-CN" ? "刷新" : "Refresh"}</button>
        </div>
      </header>

      <main className="performance-main">
        <section className="performance-intro">
          <div>
            <span className="performance-kicker">SAME STARTING BANKROLL · REAL SETTLEMENT</span>
            <h2>
              {locale === "zh-CN"
                ? "同样的赛事本金，谁真正把钱赚到了？"
                : "Same tournament bankroll. Who actually grew it?"}
            </h2>
            <p>
              {locale === "zh-CN"
                ? "每个 AI experiment 在每个赛事独立获得固定启动资金，所有 Map 共用同一资金池。这里优先看真实 shadow PnL 与风险，再下钻到预测质量、赔率延迟和逐笔仓位。"
                : "Each AI experiment receives one fixed bankroll per event and shares it across every map. Start with realized shadow P&L and risk, then drill into prediction quality, market latency, and every position."}
            </p>
          </div>
          <span className="performance-shadow-badge">SHADOW ONLY</span>
        </section>

        {leaderboard.isLoading ? (
          <StateBlock text={locale === "zh-CN" ? "正在计算 AI 排行榜…" : "Loading AI leaderboard…"} />
        ) : leaderboard.error ? (
          <StateBlock error text={locale === "zh-CN" ? "AI 排行榜加载失败。" : "Failed to load AI leaderboard."} onRetry={() => void leaderboard.refetch()} />
        ) : filtered.length === 0 ? (
          <StateBlock text={locale === "zh-CN" ? "暂无可展示的 AI 赛事账户。" : "No AI event portfolios yet."} />
        ) : (
          <>
            <section className="performance-overview-grid">
              <div className="performance-leaderboard-panel">
                <div className="performance-section-heading">
                  <div>
                    <span className="performance-kicker">LONG-RUN LEADERBOARD</span>
                    <h3>{locale === "zh-CN" ? "长期盈利排行" : "Long-run leaderboard"}</h3>
                  </div>
                  <input
                    aria-label={locale === "zh-CN" ? "搜索 AI" : "Search AI"}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder={locale === "zh-CN" ? "搜索模型 / Provider" : "Search model / provider"}
                  />
                </div>
                <div className="performance-leaderboard" role="list">
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
                    <Metric label={locale === "zh-CN" ? "累计本金" : "Starting capital"} value={money(selectedExperiment.total_initial_bankroll, locale)} />
                    <Metric label={locale === "zh-CN" ? "当前权益" : "Equity"} value={money(selectedExperiment.equity, locale)} />
                    <Metric label="ROI" value={rate(selectedExperiment.realized_roi, locale)} tone={tone(selectedExperiment.realized_roi)} />
                    <Metric label={locale === "zh-CN" ? "最差回撤" : "Worst drawdown"} value={rate(-selectedExperiment.worst_event_drawdown_pct, locale)} tone="negative" />
                    <Metric label={locale === "zh-CN" ? "盈利赛事" : "Profitable events"} value={`${selectedExperiment.profitable_events}/${selectedExperiment.event_count}`} sub={rate(selectedExperiment.profitable_event_rate, locale)} />
                    <Metric label={locale === "zh-CN" ? "投注 / 命中" : "Bets / hit rate"} value={`${selectedExperiment.bet_count}`} sub={rate(selectedExperiment.hit_rate, locale)} />
                  </div>
                  <div className="performance-version-line">
                    <span>{selectedExperiment.experiment.prompt_version}</span>
                    <span>{selectedExperiment.experiment.decision_policy_version}</span>
                    <span>{selectedExperiment.experiment.ai_view_version}</span>
                  </div>
                </section>
              )}
            </section>

            {selectedExperiment && (
              <section className="performance-event-section">
                <div className="performance-section-heading">
                  <div>
                    <span className="performance-kicker">EVENT BREAKDOWN</span>
                    <h3>{locale === "zh-CN" ? "按赛事追踪资金" : "Trace performance by event"}</h3>
                  </div>
                  <span>{locale === "zh-CN" ? "点击赛事查看资金曲线、质量与逐笔仓位" : "Select an event for equity, quality and position audit"}</span>
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
      </main>
    </div>
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
        <small>{row.experiment.model}</small>
      </span>
      <span className={`performance-table-number ${tone(row.realized_pnl)}`}>{signedMoney(row.realized_pnl, locale)}</span>
      <span className={`performance-table-number ${tone(row.realized_roi)}`}>{rate(row.realized_roi, locale)}</span>
      <span className="performance-table-number negative">{rate(-row.worst_event_drawdown_pct, locale)}</span>
      <span className="performance-table-number">{row.event_count}</span>
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
      <strong className={tone(event.realized_pnl)}>{signedMoney(event.realized_pnl, locale)}</strong>
      <span className={tone(event.realized_roi)}>{rate(event.realized_roi, locale)}</span>
      <small>{locale === "zh-CN" ? "最大回撤" : "Max DD"} {rate(-event.max_drawdown_pct, locale)}</small>
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
  if (!experiment || !policy) return <StateBlock text={locale === "zh-CN" ? "这个 AI 在该赛事还没有可评估账户。" : "No evaluable portfolio for this AI in the event."} />;

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
        <GateBadge status={experiment.gate.status} mode={experiment.gate.mode} />
      </div>

      <div className="performance-detail-metrics">
        <Metric label={locale === "zh-CN" ? "启动资金" : "Start"} value={money(portfolio.initial_bankroll, locale)} />
        <Metric label={locale === "zh-CN" ? "当前权益" : "Equity"} value={money(portfolio.equity, locale)} />
        <Metric label={locale === "zh-CN" ? "已实现盈亏" : "Realized PnL"} value={signedMoney(portfolio.realized_pnl, locale)} tone={tone(portfolio.realized_pnl)} />
        <Metric label="ROI" value={rate(portfolio.roi, locale)} tone={tone(portfolio.roi)} />
        <Metric label={locale === "zh-CN" ? "最大回撤" : "Max drawdown"} value={rate(-portfolio.max_drawdown_pct, locale)} tone="negative" />
        <Metric label={locale === "zh-CN" ? "Profit Factor" : "Profit factor"} value={decimal(portfolio.profit_factor, 2)} />
      </div>

      <div className="performance-two-column">
        <section className="performance-panel">
          <div className="performance-panel-heading">
            <div>
              <span className="performance-kicker">EQUITY CURVE</span>
              <h4>{locale === "zh-CN" ? "赛事资金曲线" : "Tournament equity"}</h4>
            </div>
            <span>{portfolio.wins}W · {portfolio.losses}L · {portfolio.rejected_bet_count} rejected</span>
          </div>
          <div className="performance-chart-wrap">
            {experiment.equity_curve.length > 1 ? (
              <Suspense fallback={<div className="performance-chart-loading">Chart…</div>}>
                <IntelligenceChart option={equityChartOption(experiment, locale)} />
              </Suspense>
            ) : (
              <div className="performance-empty-inline">{locale === "zh-CN" ? "等待更多资金流水。" : "Waiting for more ledger points."}</div>
            )}
          </div>
        </section>

        <section className="performance-panel">
          <div className="performance-panel-heading">
            <div>
              <span className="performance-kicker">QUALITY GATE</span>
              <h4>{locale === "zh-CN" ? "为什么是这个结论" : "Why this gate status"}</h4>
            </div>
            <span>SHADOW ONLY</span>
          </div>
          <div className="performance-gate-progress">
            <SampleProgress label={locale === "zh-CN" ? "已结算 Maps" : "Settled maps"} current={quality.settled_maps} target={policy.min_settled_maps} />
            <SampleProgress label={locale === "zh-CN" ? "已结算投注" : "Settled bets"} current={portfolio.bet_count} target={policy.min_settled_bets} />
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
          <MetricLine label="Brier" value={decimal(quality.average_brier_score, 3)} />
          <MetricLine label="Log Loss" value={decimal(quality.average_log_loss, 3)} />
          <MetricLine label="CLV" value={percentPoints(quality.average_clv)} tone={tone(quality.average_clv)} />
          <MetricLine label={locale === "zh-CN" ? "Brier vs 市场" : "Brier vs market"} value={decimal(quality.market_comparison.brier_improvement_vs_market, 3)} tone={tone(quality.market_comparison.brier_improvement_vs_market)} />
          <MetricLine label={locale === "zh-CN" ? "平均仓位 / 现金" : "Avg stake / cash"} value={rate(quality.average_stake_pct_of_available_cash, locale)} />
          <MetricLine label={locale === "zh-CN" ? "最长连败" : "Longest losing streak"} value={`${quality.longest_losing_streak}`} />
        </section>

        <section className="performance-panel compact performance-latency-panel">
          <span className="performance-kicker">ACTIONABLE AFTER RESPONSE</span>
          <h4>{locale === "zh-CN" ? "AI 给答案后，edge 还在吗？" : "Does the edge survive after the AI answers?"}</h4>
          <div className="performance-latency-grid">
            {Object.entries(experiment.execution_latency.horizons).map(([horizon, row]) => (
              <div key={horizon} className="performance-latency-cell">
                <strong>T+{horizon}s</strong>
                <span>{locale === "zh-CN" ? "可执行率" : "Actionable"} {rate(row.actionable_rate, locale)}</span>
                <span>{locale === "zh-CN" ? "赔率变化" : "Odds move"} {rate(row.average_odds_slippage_pct, locale)}</span>
                <small>n={row.sample_count}</small>
              </div>
            ))}
            {Object.keys(experiment.execution_latency.horizons).length === 0 && (
              <div className="performance-empty-inline">{locale === "zh-CN" ? "暂无 response 后赔率样本。" : "No post-response market samples yet."}</div>
            )}
          </div>
          <p className="performance-method-note">
            {locale === "zh-CN"
              ? "纸面市场观测，不代表博彩公司实际接受了订单。AI response 之前的赔率不会进入 actionable rate。"
              : "Paper market observation, not bookmaker execution confirmation. Captures before the AI response are excluded."}
          </p>
        </section>

        <section className="performance-panel compact">
          <span className="performance-kicker">RISK / ACTIVITY</span>
          <h4>{locale === "zh-CN" ? "风险与交易行为" : "Risk and activity"}</h4>
          <MetricLine label={locale === "zh-CN" ? "投注次数" : "Settled bets"} value={`${portfolio.bet_count}`} />
          <MetricLine label={locale === "zh-CN" ? "命中率" : "Hit rate"} value={rate(portfolio.hit_rate, locale)} />
          <MetricLine label={locale === "zh-CN" ? "总投注额" : "Turnover"} value={money(portfolio.turnover, locale)} />
          <MetricLine label={locale === "zh-CN" ? "最大单笔 / 现金" : "Largest stake / cash"} value={rate(quality.largest_stake_pct_of_available_cash, locale)} />
          <MetricLine label={locale === "zh-CN" ? "锁定资金" : "Locked capital"} value={money(portfolio.locked_balance, locale)} />
          <MetricLine label={locale === "zh-CN" ? "账户状态" : "Account status"} value={portfolio.status} />
        </section>
      </div>

      <section className="performance-panel performance-position-panel">
        <div className="performance-panel-heading">
          <div>
            <span className="performance-kicker">POSITION AUDIT</span>
            <h4>{locale === "zh-CN" ? "逐笔追溯：这些钱是怎么赚 / 亏的" : "Position audit: where the P&L came from"}</h4>
          </div>
          <span>{positions.length} positions</span>
        </div>
        {positionsLoading ? (
          <div className="performance-empty-inline">{locale === "zh-CN" ? "正在读取仓位流水…" : "Loading position audit…"}</div>
        ) : positionsError ? (
          <button className="performance-retry" type="button" onClick={onRetryPositions}>{locale === "zh-CN" ? "仓位加载失败 · 重试" : "Position audit failed · Retry"}</button>
        ) : positions.length === 0 ? (
          <div className="performance-empty-inline">{locale === "zh-CN" ? "这个赛事还没有 BUY 仓位。" : "No BUY positions in this event yet."}</div>
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
        <span><b>MAP {position.map_number ?? "?"}</b><small>{formatDateTime(position.opened_at, locale)}</small></span>
        <span><b>{position.action.replace("_", " ")}</b><small>{locale === "zh-CN" ? "AI 操作" : "AI action"}</small></span>
        <span><b>{money(position.stake, locale)}</b><small>@ {position.odds?.toFixed(3) ?? "—"}</small></span>
        <span className={`position-status status-${position.status.toLowerCase()}`}>{position.status}</span>
        <span className={tone(position.realized_pnl)}><b>{position.realized_pnl == null ? "—" : signedMoney(position.realized_pnl, locale)}</b><small>{locale === "zh-CN" ? "已实现 PnL" : "Realized PnL"}</small></span>
        <span className="performance-chevron">{expanded ? "−" : "+"}</span>
      </button>
      {expanded && (
        <div className="performance-position-detail">
          <DetailDatum label={locale === "zh-CN" ? "成交前现金" : "Cash before"} value={money(position.cash_before, locale)} />
          <DetailDatum label={locale === "zh-CN" ? "返还" : "Payout"} value={position.payout == null ? "—" : money(position.payout, locale)} />
          <DetailDatum label={locale === "zh-CN" ? "拒绝原因" : "Rejection"} value={position.rejection_reason ?? "—"} />
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

function GateBadge({ status, mode }: { status: string; mode: string }) {
  return <div className={`performance-gate-badge gate-${status.toLowerCase()}`}><strong>{status}</strong><span>{mode}</span></div>;
}

function PnlBadge({ value, locale }: { value: number; locale: string }) {
  return <div className={`performance-pnl-badge ${tone(value)}`}><span>{locale === "zh-CN" ? "累计 PnL" : "Total PnL"}</span><strong>{signedMoney(value, locale)}</strong></div>;
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
  return [identity.provider, identity.model, identity.prompt_version, identity.decision_policy_version, identity.ai_view_version].join("\u0000");
}

function sameIdentity(left: AiExperimentIdentity, right: AiExperimentIdentity): boolean {
  return identityKey(left) === identityKey(right);
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
        name: locale === "zh-CN" ? "权益" : "Equity",
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

function failureLabel(value: string, locale: string): string {
  if (locale !== "zh-CN") return value.replaceAll("_", " ");
  const labels: Record<string, string> = {
    MIN_SETTLED_MAPS: "已结算地图样本不足",
    MIN_SETTLED_BETS: "已结算投注不足",
    MIN_PREDICTION_SAMPLES: "独立预测样本不足",
    MIN_CLV_SAMPLES: "CLV 样本不足",
    MIN_MARKET_COMPARISON_SAMPLES: "市场对照样本不足",
    ROI: "ROI 未达标",
    CLV: "CLV 未达标",
    BRIER_VS_MARKET: "Brier 未优于市场",
    MAX_DRAWDOWN: "最大回撤超阈值",
    BANKRUPTCY: "发生破产"
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

function percentPoints(value: number | null): string {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}pp`;
}

function decimal(value: number | null, digits: number): string {
  return value == null ? "—" : value.toFixed(digits);
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
