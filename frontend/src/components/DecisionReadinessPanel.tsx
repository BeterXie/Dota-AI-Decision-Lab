import React, { useMemo, useState } from "react";
import type {
  AiReadinessFailureReason,
  AiReadinessPayload,
  AiReadinessSeries,
  AiReadinessStage
} from "../performanceApi";
import "./decision-readiness.css";

export function DecisionReadinessPanel({
  data,
  loading,
  error,
  onRetry,
  locale
}: {
  data: AiReadinessPayload | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  locale: string;
}) {
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [selectedReason, setSelectedReason] = useState<string | null>(null);
  const blockedSeries = useMemo(() => {
    const rows = (data?.series ?? []).filter((series) => series.blocker !== null);
    return rows.filter((series) => {
      if (selectedReason && series.blocker?.reason !== selectedReason) return false;
      if (selectedStage && series.blocker?.stage !== selectedStage) return false;
      return true;
    });
  }, [data?.series, selectedReason, selectedStage]);

  if (loading) {
    return <ReadinessState text={locale === "zh-CN" ? "正在计算真实比赛决策漏斗…" : "Calculating real-match readiness…"} />;
  }
  if (error) {
    return (
      <ReadinessState
        error
        text={locale === "zh-CN" ? "决策就绪度加载失败。" : "Failed to load decision readiness."}
        onRetry={onRetry}
      />
    );
  }
  if (!data || data.scope.series_count === 0) {
    return (
      <ReadinessState
        text={
          locale === "zh-CN"
            ? "过去 7 天还没有已开赛的 Liquipedia canonical series。"
            : "No elapsed Liquipedia-backed series in the last 7 days yet."
        }
      />
    );
  }

  const evaluated = data.stages.find((stage) => stage.key === "evaluated")?.count ?? 0;
  const total = data.scope.series_count;

  return (
    <section className="performance-readiness" aria-label={locale === "zh-CN" ? "决策就绪度" : "Decision readiness"}>
      <div className="performance-section-heading readiness-heading">
        <div>
          <span className="performance-kicker">PRODUCTION SHADOW VALIDATION</span>
          <h3>{locale === "zh-CN" ? "真实比赛决策就绪度" : "Real-match decision readiness"}</h3>
        </div>
        <span>
          {locale === "zh-CN"
            ? `过去 ${Math.round(data.window.lookback_hours / 24)} 天 · 不含未来比赛`
            : `Last ${Math.round(data.window.lookback_hours / 24)} days · future matches excluded`}
        </span>
      </div>

      <div className="readiness-summary">
        <div>
          <strong>{total}</strong>
          <span>{locale === "zh-CN" ? "进入验证的真实系列赛" : "real series observed"}</span>
        </div>
        <div>
          <strong>{evaluated}</strong>
          <span>{locale === "zh-CN" ? "完成 AI 评价闭环" : "fully evaluated"}</span>
        </div>
        <div>
          <strong>{percent(total ? evaluated / total : null, locale)}</strong>
          <span>{locale === "zh-CN" ? "端到端闭环率" : "end-to-end completion"}</span>
        </div>
      </div>

      <div className="readiness-funnel" aria-label={locale === "zh-CN" ? "决策漏斗" : "Decision funnel"}>
        {data.stages.map((stage) => (
          <StageCard
            key={stage.key}
            stage={stage}
            locale={locale}
            active={selectedStage === stage.key}
            onSelect={() => {
              setSelectedReason(null);
              setSelectedStage((current) => (current === stage.key ? null : stage.key));
            }}
          />
        ))}
      </div>

      <div className="readiness-lower-grid">
        <section className="performance-panel readiness-blockers">
          <div className="performance-panel-heading">
            <div>
              <span className="performance-kicker">FIRST UNRESOLVED BLOCKER</span>
              <h4>{locale === "zh-CN" ? "掉点原因" : "Where series stop"}</h4>
            </div>
            {(selectedStage || selectedReason) && (
              <button
                type="button"
                className="readiness-clear"
                onClick={() => {
                  setSelectedStage(null);
                  setSelectedReason(null);
                }}
              >
                {locale === "zh-CN" ? "清除筛选" : "Clear filter"}
              </button>
            )}
          </div>
          <div className="readiness-reasons">
            {data.failure_reasons.length === 0 ? (
              <p className="performance-method-note">
                {locale === "zh-CN" ? "当前窗口没有未闭环系列赛。" : "No unresolved series in this window."}
              </p>
            ) : (
              data.failure_reasons.map((reason) => (
                <ReasonButton
                  key={`${reason.stage}:${reason.reason}`}
                  reason={reason}
                  locale={locale}
                  active={selectedReason === reason.reason}
                  onSelect={() => {
                    setSelectedStage(null);
                    setSelectedReason((current) => (current === reason.reason ? null : reason.reason));
                  }}
                />
              ))
            )}
          </div>
        </section>

        <section className="performance-panel readiness-trace">
          <div className="performance-panel-heading">
            <div>
              <span className="performance-kicker">TRACE TO SERIES</span>
              <h4>{locale === "zh-CN" ? "具体卡在哪些比赛" : "Trace blocked series"}</h4>
            </div>
            <span>{blockedSeries.length}</span>
          </div>
          <div className="readiness-series-list">
            {blockedSeries.length === 0 ? (
              <p className="performance-method-note">
                {locale === "zh-CN" ? "这个筛选下没有未闭环系列赛。" : "No unresolved series for this filter."}
              </p>
            ) : (
              blockedSeries.slice(0, 12).map((series) => (
                <SeriesTrace key={series.canonical_series_id} series={series} locale={locale} />
              ))
            )}
          </div>
          {blockedSeries.length > 12 && (
            <p className="performance-method-note">
              {locale === "zh-CN"
                ? `还有 ${blockedSeries.length - 12} 场未显示；API 保留完整追踪记录。`
                : `${blockedSeries.length - 12} more series are available in the API trace.`}
            </p>
          )}
        </section>
      </div>
    </section>
  );
}

function StageCard({
  stage,
  locale,
  active,
  onSelect
}: {
  stage: AiReadinessStage;
  locale: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`readiness-stage ${active ? "active" : ""}`}
      onClick={onSelect}
      aria-pressed={active}
    >
      <span>{stageLabel(stage.key, locale)}</span>
      <strong>{stage.count}</strong>
      <small>{percent(stage.rate, locale)}</small>
      {stage.drop_count > 0 && (
        <em>-{stage.drop_count} {locale === "zh-CN" ? "掉点" : "drop"}</em>
      )}
    </button>
  );
}

function ReasonButton({
  reason,
  locale,
  active,
  onSelect
}: {
  reason: AiReadinessFailureReason;
  locale: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`readiness-reason ${active ? "active" : ""}`}
      onClick={onSelect}
      aria-pressed={active}
    >
      <span>{reasonLabel(reason.reason, locale)}</span>
      <strong>{reason.count}</strong>
      <small>{percent(reason.rate, locale)}</small>
    </button>
  );
}

function SeriesTrace({ series, locale }: { series: AiReadinessSeries; locale: string }) {
  return (
    <div className="readiness-series-row">
      <div className="readiness-series-main">
        <span>{series.event_name || (locale === "zh-CN" ? "未知赛事" : "Unknown event")}</span>
        <strong>{series.team_a.name} <i>vs</i> {series.team_b.name}</strong>
        <small>{formatDate(series.scheduled_at, locale)}</small>
      </div>
      <div className="readiness-series-status">
        <span>{stageLabelFromBackend(series.current_stage, locale)}</span>
        <strong>{series.blocker ? reasonLabel(series.blocker.reason, locale) : "—"}</strong>
        <small>
          {locale === "zh-CN" ? "Map/Live/快照/AI/评价" : "Maps/Live/Snapshots/AI/Eval"}: {series.counts.maps}/{series.counts.live_maps}/{series.counts.snapshots}/{series.counts.successful_decision_snapshots}/{series.counts.evaluated_snapshots}
        </small>
      </div>
    </div>
  );
}

function ReadinessState({ text, error, onRetry }: { text: string; error?: boolean; onRetry?: () => void }) {
  return (
    <section className={`performance-state readiness-state ${error ? "error" : ""}`}>
      <span>{text}</span>
      {onRetry && <button onClick={onRetry}>{"Retry"}</button>}
    </section>
  );
}

function stageLabel(key: string, locale: string): string {
  const zh: Record<string, string> = {
    scheduled: "赛程进入",
    raybet_linked: "RayBet 绑定",
    market_ready: "赔率可用",
    map_identity: "Map 身份",
    live_ready: "实时数据",
    snapshot_ready: "特征快照",
    ai_decision: "AI 决策",
    result_ready: "赛果可用",
    evaluated: "完成评价"
  };
  const en: Record<string, string> = {
    scheduled: "Scheduled",
    raybet_linked: "RayBet linked",
    market_ready: "Market ready",
    map_identity: "Map identity",
    live_ready: "Live data",
    snapshot_ready: "Feature snapshot",
    ai_decision: "AI decision",
    result_ready: "Result ready",
    evaluated: "Evaluated"
  };
  return (locale === "zh-CN" ? zh : en)[key] ?? key;
}

function stageLabelFromBackend(stage: string, locale: string): string {
  const key = stage.toLocaleLowerCase().replaceAll("_", " ");
  const match = Object.entries({
    scheduled: "SCHEDULED",
    raybet_linked: "RAYBET_LINKED",
    market_ready: "MARKET_READY",
    map_identity: "MAP_IDENTITY",
    live_ready: "LIVE_READY",
    snapshot_ready: "SNAPSHOT_READY",
    ai_decision: "AI_DECISION",
    result_ready: "RESULT_READY",
    evaluated: "EVALUATED"
  }).find(([, value]) => value === stage);
  return match ? stageLabel(match[0], locale) : key;
}

function reasonLabel(reason: string, locale: string): string {
  const zh: Record<string, string> = {
    RAYBET_IDENTITY_MISSING: "RayBet 身份未匹配",
    MARKET_OBSERVATION_MISSING: "缺少市场赔率",
    CANONICAL_MAP_MISSING: "Map 身份未建立",
    DLTV_LIVE_MISSING: "缺少 DLTV 实时数据",
    DRAFT_MISSING: "缺少选人快照",
    DRAFT_INCOMPLETE: "选人数据不完整",
    DRAFT_CURVE_MISSING: "选人强度曲线缺失",
    SNAPSHOT_GATE_BLOCKED: "特征快照 Gate 未通过",
    AI_DECISION_MISSING: "AI 决策未产生",
    RESULT_MISSING: "赛果未解析",
    EVALUATION_MISSING: "AI 评价未完成"
  };
  const en: Record<string, string> = {
    RAYBET_IDENTITY_MISSING: "RayBet identity missing",
    MARKET_OBSERVATION_MISSING: "Market odds missing",
    CANONICAL_MAP_MISSING: "Map identity missing",
    DLTV_LIVE_MISSING: "DLTV live data missing",
    DRAFT_MISSING: "Draft snapshot missing",
    DRAFT_INCOMPLETE: "Draft incomplete",
    DRAFT_CURVE_MISSING: "Draft curve missing",
    SNAPSHOT_GATE_BLOCKED: "Snapshot gate blocked",
    AI_DECISION_MISSING: "AI decision missing",
    RESULT_MISSING: "Result missing",
    EVALUATION_MISSING: "Evaluation missing"
  };
  const known = (locale === "zh-CN" ? zh : en)[reason];
  if (known) return known;
  if (reason.startsWith("AI_")) {
    const status = reason.slice(3).replaceAll("_", " ");
    return locale === "zh-CN" ? `AI 失败：${status}` : `AI failed: ${status}`;
  }
  return reason.replaceAll("_", " ");
}

function percent(value: number | null, locale: string): string {
  if (value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    style: "percent",
    maximumFractionDigits: 0
  }).format(value);
}

function formatDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}
