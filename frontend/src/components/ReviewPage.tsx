import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import {
  fetchReviewMatches,
  type ReviewAiGroup,
  type ReviewMatch,
  type ReviewRoshEdge
} from "../reviewApi";
import "./ReviewPage.css";

type ReviewFilter = "ALL" | "ROSH_WRONG" | "AI_BUY" | "CLOSING";

export function ReviewPage() {
  const { locale, setLocale } = useI18n();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<ReviewFilter>("ALL");
  const review = useQuery({
    queryKey: ["review-matches"],
    queryFn: () => fetchReviewMatches(100),
    refetchInterval: 30_000
  });

  const rows = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return (review.data?.matches ?? []).filter((match) => {
      if (query) {
        const haystack = `${match.team_a.name} ${match.team_b.name} ${match.tournament_name ?? ""}`.toLocaleLowerCase();
        if (!haystack.includes(query)) return false;
      }
      if (filter === "ROSH_WRONG") return match.rosh?.reference?.adjusted.correct === false;
      if (filter === "AI_BUY") return match.ai.some((item) => item.buy_decisions > 0);
      if (filter === "CLOSING") return match.odds?.end_kind === "CLOSING";
      return true;
    });
  }, [review.data?.matches, search, filter]);

  const summary = review.data?.summary;
  return (
    <div className="review-page">
      <header className="review-header">
        <div className="review-brand">
          <a href="/" className="review-back">← {locale === "zh-CN" ? "实时看盘" : "Live dashboard"}</a>
          <div><span className="review-kicker">DOTA AI DECISION LAB</span><h1>{locale === "zh-CN" ? "比赛复盘" : "Match Review"}</h1></div>
        </div>
        <div className="review-header-actions">
          <button className={locale === "zh-CN" ? "active" : ""} onClick={() => setLocale("zh-CN")}>中文</button>
          <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}>EN</button>
          <button onClick={() => void review.refetch()}>{locale === "zh-CN" ? "刷新" : "Refresh"}</button>
        </div>
      </header>

      <main className="review-main">
        <section className="review-intro">
          <div>
            <span className="review-kicker">POST-MATCH ANALYTICS</span>
            <h2>{locale === "zh-CN" ? "用同一张表看阵容、AI 与市场到底准不准" : "One view for draft, AI and market performance"}</h2>
            <p>{locale === "zh-CN"
              ? "R.O.S.H. 使用当时冻结的 DecisionSnapshot 阵容曲线；AI 重跑按同一 checkpoint 只计一次；赔率起点是首个可决策快照，不伪装成真实开盘价。"
              : "R.O.S.H. uses the curve frozen in the original DecisionSnapshot. AI reruns count once per checkpoint, and the odds start is the first decision-eligible snapshot rather than a claimed bookmaker open."}</p>
          </div>
          <div className="review-method-pill">{locale === "zh-CN" ? "无赛后信息回填" : "No post-match leakage"}</div>
        </section>

        {review.isLoading && <div className="review-state">{locale === "zh-CN" ? "正在读取复盘数据…" : "Loading review data…"}</div>}
        {review.error && <div className="review-state error">{review.error.message}</div>}

        {summary && (
          <>
            <section className="review-kpis">
              <Kpi label={locale === "zh-CN" ? "已结算地图" : "Settled maps"} value={`${summary.settled_maps}`} />
              <Kpi
                label={locale === "zh-CN" ? `R.O.S.H. 纯阵容 ${summary.rosh.reference_minute}m` : `R.O.S.H. pure ${summary.rosh.reference_minute}m`}
                value={accuracyLabel(summary.rosh.pure.correct, summary.rosh.pure.evaluated, locale)}
                sub={rate(summary.rosh.pure.accuracy, locale)}
              />
              <Kpi
                label={locale === "zh-CN" ? `R.O.S.H. 选手修正 ${summary.rosh.reference_minute}m` : `R.O.S.H. adjusted ${summary.rosh.reference_minute}m`}
                value={accuracyLabel(summary.rosh.adjusted.correct, summary.rosh.adjusted.evaluated, locale)}
                sub={rate(summary.rosh.adjusted.accuracy, locale)}
              />
              <Kpi
                label={locale === "zh-CN" ? "收盘赔率覆盖" : "Closing odds coverage"}
                value={`${summary.odds.closing_captured}/${summary.odds.eligible_maps}`}
                sub={rate(summary.odds.closing_coverage, locale)}
              />
            </section>

            <section className="review-model-board">
              <div className="review-section-heading">
                <div><span className="review-kicker">AI SCOREBOARD</span><h3>{locale === "zh-CN" ? "模型整体表现" : "Model performance"}</h3></div>
                <span>{locale === "zh-CN" ? "BUY 命中只统计 BUY_A / BUY_B；Brier 越低越好" : "BUY accuracy counts BUY_A / BUY_B only; lower Brier is better"}</span>
              </div>
              <div className="review-model-grid">
                {summary.ai.map((item) => <ModelSummary key={`${item.provider}:${item.model}`} item={item} locale={locale} />)}
                {summary.ai.length === 0 && <div className="review-empty">{locale === "zh-CN" ? "暂无已评估 AI 决策" : "No evaluated AI decisions yet"}</div>}
              </div>
            </section>
          </>
        )}

        <section className="review-list-section">
          <div className="review-list-toolbar">
            <div><span className="review-kicker">MATCH LEDGER</span><h3>{locale === "zh-CN" ? "复盘比赛列表" : "Review ledger"}</h3></div>
            <div className="review-controls">
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={locale === "zh-CN" ? "搜索队伍 / 赛事" : "Search team / event"} />
              <div className="review-filter-group">
                {([
                  ["ALL", locale === "zh-CN" ? "全部" : "All"],
                  ["ROSH_WRONG", locale === "zh-CN" ? "ROSH 错误" : "ROSH misses"],
                  ["AI_BUY", locale === "zh-CN" ? "有 AI BUY" : "AI BUY"],
                  ["CLOSING", locale === "zh-CN" ? "有收盘" : "Closing captured"]
                ] as Array<[ReviewFilter, string]>).map(([key, label]) => (
                  <button key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}</button>
                ))}
              </div>
            </div>
          </div>

          <div className="review-match-list">
            {rows.map((match) => <MatchReviewCard key={match.canonical_map_id} match={match} locale={locale} />)}
            {!review.isLoading && rows.length === 0 && <div className="review-empty">{locale === "zh-CN" ? "当前筛选条件没有比赛" : "No matches for this filter"}</div>}
          </div>
        </section>
      </main>
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="review-kpi"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

function ModelSummary({ item, locale }: { item: ReviewAiGroup; locale: string }) {
  return (
    <article className="review-model-card">
      <div className="review-model-title"><strong>{providerLabel(item.provider)}</strong><span>{item.model}</span></div>
      <div className="review-model-metrics">
        <Metric label={locale === "zh-CN" ? "BUY 命中" : "BUY accuracy"} value={item.settled_buy_decisions ? `${item.correct_buy_decisions}/${item.settled_buy_decisions} · ${rate(item.buy_accuracy, locale)}` : "—"} />
        <Metric label="Brier" value={decimal(item.average_brier, 3)} />
        <Metric label={locale === "zh-CN" ? "1单位 ROI" : "1-unit ROI"} value={rate(item.unit_roi, locale)} tone={tone(item.unit_roi)} />
        <Metric label={locale === "zh-CN" ? "决策轮数" : "Rounds"} value={`${item.rounds}`} />
      </div>
    </article>
  );
}

function MatchReviewCard({ match, locale }: { match: ReviewMatch; locale: string }) {
  const winnerA = match.winner_team_id === match.team_a.id;
  const winnerB = match.winner_team_id === match.team_b.id;
  const winner = winnerA ? match.team_a : winnerB ? match.team_b : null;
  return (
    <article className="review-match-card">
      <div className="review-match-head">
        <div className="review-match-meta">
          <span>{formatDate(match.settled_at, locale)}</span>
          {match.tournament_name && <span>{match.tournament_name}</span>}
          {match.map_number != null && <span>MAP {match.map_number}</span>}
        </div>
        <div className="review-versus">
          <TeamName team={match.team_a.name} winner={winnerA} />
          <span className="review-vs">VS</span>
          <TeamName team={match.team_b.name} winner={winnerB} />
        </div>
      </div>

      <div className="review-match-grid">
        <div className="review-cell rosh-cell">
          <span className="review-cell-label">R.O.S.H.</span>
          {match.rosh ? (
            <>
              <div className="rosh-reference-line">
                <RoshScore label={locale === "zh-CN" ? "纯阵容" : "Pure"} edge={match.rosh.reference?.pure ?? null} match={match} />
                <RoshScore label={locale === "zh-CN" ? "选手修正" : "Adjusted"} edge={match.rosh.reference?.adjusted ?? null} match={match} />
              </div>
              <div className="rosh-timeline">
                {match.rosh.points.map((point) => (
                  <span key={point.minute}>{point.minute}m <b>{edgeShort(point.adjusted, match)}</b></span>
                ))}
              </div>
            </>
          ) : <span className="review-muted">{locale === "zh-CN" ? "无可审计阵容快照" : "No auditable draft snapshot"}</span>}
        </div>

        <div className="review-cell result-cell">
          <span className="review-cell-label">{locale === "zh-CN" ? "获胜方" : "Winner"}</span>
          <strong className="winner-name">🏆 {winner?.name ?? "—"}</strong>
          <small>{locale === "zh-CN" ? "最终 Map 结果" : "Final map result"}</small>
        </div>

        <div className="review-cell ai-cell">
          <span className="review-cell-label">{locale === "zh-CN" ? "AI 决策" : "AI decisions"}</span>
          <div className="review-ai-list">
            {match.ai.map((item) => <AiBadge key={`${item.provider}:${item.model}`} item={item} match={match} locale={locale} />)}
            {match.ai.length === 0 && <span className="review-muted">—</span>}
          </div>
        </div>

        <div className="review-cell odds-cell">
          <span className="review-cell-label">{locale === "zh-CN" ? "赔率变化" : "Odds movement"}</span>
          {match.odds ? (
            <>
              <div className="odds-team-line"><span>{match.team_a.name}</span><strong>{match.odds.start.odds_a.toFixed(2)} → {match.odds.end.odds_a.toFixed(2)}</strong></div>
              <div className="odds-team-line"><span>{match.team_b.name}</span><strong>{match.odds.start.odds_b.toFixed(2)} → {match.odds.end.odds_b.toFixed(2)}</strong></div>
              <div className="odds-delta">A fair p {signedPp(match.odds.team_a_fair_probability_change_pp)} · {match.odds.end_kind === "CLOSING" ? (locale === "zh-CN" ? "收盘" : "closing") : (locale === "zh-CN" ? "最后决策" : "last decision")}</div>
            </>
          ) : <span className="review-muted">{locale === "zh-CN" ? "无有效赔率对" : "No valid odds pair"}</span>}
        </div>
      </div>
    </article>
  );
}

function TeamName({ team, winner }: { team: string; winner: boolean }) {
  return <strong className={winner ? "review-team winner" : "review-team"}>{team}{winner && <span className="winner-trophy" title="Winner">🏆</span>}</strong>;
}

function RoshScore({ label, edge, match }: { label: string; edge: ReviewRoshEdge | null; match: ReviewMatch }) {
  if (!edge || edge.edge_pp == null) return <div><span>{label}</span><strong>—</strong></div>;
  const team = edge.favored_team_id === match.team_a.id ? match.team_a.name : edge.favored_team_id === match.team_b.id ? match.team_b.name : "EVEN";
  return <div className={edge.correct === true ? "correct" : edge.correct === false ? "wrong" : "neutral"}><span>{label}</span><strong>{team} {edge.favored_team_id ? `+${Math.abs(edge.edge_pp).toFixed(1)}pp` : "≈0"} {edge.correct === true ? "✓" : edge.correct === false ? "✕" : ""}</strong></div>;
}

function AiBadge({ item, match, locale }: { item: ReviewAiGroup; match: ReviewMatch; locale: string }) {
  const action = item.latest?.action ?? "—";
  const actionTeam = action === "BUY_A" ? match.team_a.name : action === "BUY_B" ? match.team_b.name : null;
  return (
    <div className="review-ai-badge">
      <div><strong>{providerLabel(item.provider)}</strong><span>{actionTeam ? `${action.replace("_", " ")} · ${actionTeam}` : action.replaceAll("_", " ")}</span></div>
      <small>{item.settled_buy_decisions > 0 ? `${item.correct_buy_decisions}/${item.settled_buy_decisions} ${locale === "zh-CN" ? "命中" : "correct"}` : (locale === "zh-CN" ? "无已结算 BUY" : "no settled BUY")}{item.latest?.confidence != null ? ` · conf ${rate(item.latest.confidence, locale)}` : ""}</small>
    </div>
  );
}

function Metric({ label, value, tone: toneClass }: { label: string; value: string; tone?: string }) {
  return <div><span>{label}</span><strong className={toneClass}>{value}</strong></div>;
}

function edgeShort(edge: ReviewRoshEdge, match: ReviewMatch): string {
  if (edge.edge_pp == null || edge.favored_team_id == null) return "—";
  const side = edge.favored_team_id === match.team_a.id ? "A" : edge.favored_team_id === match.team_b.id ? "B" : "?";
  return `${side} +${Math.abs(edge.edge_pp).toFixed(1)}`;
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

function accuracyLabel(correct: number, evaluated: number, locale: string): string {
  return evaluated ? `${correct}/${evaluated}` : (locale === "zh-CN" ? "暂无" : "N/A");
}
function rate(value: number | null, locale: string): string {
  return value == null ? "—" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}
function decimal(value: number | null, digits: number): string { return value == null ? "—" : value.toFixed(digits); }
function signedPp(value: number | null): string { return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(1)}pp`; }
function tone(value: number | null): string { return value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : ""; }
function formatDate(value: string, locale: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}
