import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PRODUCT_NAME } from "../brand";
import { translate, useI18n, type Locale } from "../i18n";
import {
  fetchReviewMatches,
  type ReviewAiGroup,
  type ReviewMatch,
  type ReviewRoshEdge
} from "../reviewApi";
import { getOfficialEventDisplayName } from "../utils/officialVisuals";
import "./ReviewPage.css";

type ReviewFilter = "ALL" | "ROSH_WRONG" | "AI_PREDICTION" | "CLOSING";

export function ReviewPage() {
  const { locale, setLocale, t } = useI18n();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<ReviewFilter>("ALL");
  const review = useQuery({
    queryKey: ["review-matches"],
    queryFn: () => fetchReviewMatches(100),
    staleTime: 30_000,
    refetchInterval: 60_000
  });

  const rows = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return (review.data?.matches ?? []).filter((match) => {
      if (query) {
        const haystack = `${match.team_a.name} ${match.team_b.name} ${match.tournament_name ?? ""}`.toLocaleLowerCase();
        if (!haystack.includes(query)) return false;
      }
      if (filter === "ROSH_WRONG") return match.rosh?.reference?.adjusted.correct === false;
      if (filter === "AI_PREDICTION") return match.ai.some((item) => item.buy_decisions > 0);
      if (filter === "CLOSING") return match.odds?.end_kind === "CLOSING";
      return true;
    });
  }, [review.data?.matches, search, filter]);

  const summary = review.data?.summary;
  return (
    <div className="review-page">
      <header className="review-header">
        <div className="review-brand">
          <a href="/" className="review-back">← {t("reviewLiveDashboard")}</a>
          <div><span className="review-kicker">{PRODUCT_NAME.toUpperCase()}</span><h1>{t("reviewTitle")}</h1></div>
        </div>
        <div className="review-header-actions">
          <button className={locale === "zh-CN" ? "active" : ""} onClick={() => setLocale("zh-CN")}>中文</button>
          <button className={locale === "en" ? "active" : ""} onClick={() => setLocale("en")}>EN</button>
          <button onClick={() => void review.refetch()}>{t("refreshData")}</button>
        </div>
      </header>

      <div className="review-main">
        <section className="review-intro">
          <div>
            <span className="review-kicker">POST-MATCH ANALYTICS</span>
            <h2>{t("reviewHeadline")}</h2>
            <p>{t("reviewDescription")}</p>
          </div>
          <div className="review-method-pill">{t("reviewNoLeakage")}</div>
        </section>

        {review.isLoading && <div className="review-state">{t("reviewLoading")}</div>}
        {review.error && <div className="review-state error">{review.error.message}</div>}

        {summary && (
          <>
            <section className="review-kpis">
              <Kpi label={t("reviewSettledMaps")} value={`${summary.settled_maps}`} />
              <Kpi
                label={`${t("reviewRoshPure")} ${summary.rosh.reference_minute}m`}
                value={accuracyLabel(summary.rosh.pure.correct, summary.rosh.pure.evaluated, locale)}
                sub={rate(summary.rosh.pure.accuracy, locale)}
              />
              <Kpi
                label={`${t("reviewRoshAdjusted")} ${summary.rosh.reference_minute}m`}
                value={accuracyLabel(summary.rosh.adjusted.correct, summary.rosh.adjusted.evaluated, locale)}
                sub={rate(summary.rosh.adjusted.accuracy, locale)}
              />
              <Kpi
                label={t("reviewClosingCoverage")}
                value={`${summary.odds.closing_captured}/${summary.odds.eligible_maps}`}
                sub={rate(summary.odds.closing_coverage, locale)}
              />
            </section>

            <section className="review-model-board">
              <div className="review-section-heading">
                <div><span className="review-kicker">AI SCOREBOARD</span><h3>{t("reviewModelPerformance")}</h3></div>
                <span>{t("reviewModelHint")}</span>
              </div>
              <div className="review-model-grid">
                {summary.ai.map((item) => <ModelSummary key={`${item.provider}:${item.model}`} item={item} locale={locale} />)}
                {summary.ai.length === 0 && <div className="review-empty">{t("reviewNoEvaluatedAi")}</div>}
              </div>
            </section>
          </>
        )}

        <section className="review-list-section">
          <div className="review-list-toolbar">
            <div><span className="review-kicker">MATCH LEDGER</span><h3>{t("reviewLedger")}</h3></div>
            <div className="review-controls">
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("reviewSearchPlaceholder")} />
              <div className="review-filter-group">
                {([
                  ["ALL", t("reviewFilterAll")],
                  ["ROSH_WRONG", t("reviewFilterRoshMiss")],
                  ["AI_PREDICTION", t("reviewFilterAiBuy")],
                  ["CLOSING", t("reviewFilterClosing")]
                ] as Array<[ReviewFilter, string]>).map(([key, label]) => (
                  <button key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}</button>
                ))}
              </div>
            </div>
          </div>

          <div className="review-match-list">
            {rows.map((match) => <MatchReviewCard key={match.canonical_map_id} match={match} locale={locale} />)}
            {!review.isLoading && rows.length === 0 && <div className="review-empty">{t("reviewNoMatches")}</div>}
          </div>
        </section>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="review-kpi"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

function ModelSummary({ item, locale }: { item: ReviewAiGroup; locale: Locale }) {
  return (
    <article className="review-model-card">
      <div className="review-model-title"><strong>{providerLabel(item.provider)}</strong><span>{item.model}</span></div>
      <div className="review-model-metrics">
        <Metric label={translate("reviewBuyAccuracy", locale)} value={item.settled_buy_decisions ? `${item.correct_buy_decisions}/${item.settled_buy_decisions} · ${rate(item.buy_accuracy, locale)}` : "—"} />
        <Metric label="Brier" value={decimal(item.average_brier, 3)} />
        <Metric label={translate("reviewOneUnitRoi", locale)} value={rate(item.unit_roi, locale)} tone={tone(item.unit_roi)} />
        <Metric label={translate("reviewRounds", locale)} value={`${item.rounds}`} />
      </div>
    </article>
  );
}

function MatchReviewCard({ match, locale }: { match: ReviewMatch; locale: Locale }) {
  const winnerA = match.winner_team_id === match.team_a.id;
  const winnerB = match.winner_team_id === match.team_b.id;
  const winner = winnerA ? match.team_a : winnerB ? match.team_b : null;
  return (
    <article className="review-match-card">
      <div className="review-match-head">
        <div className="review-match-meta">
          <span>{formatDate(match.settled_at, locale)}</span>
          {match.tournament_name && <span>{getOfficialEventDisplayName(match.tournament_name)}</span>}
          {match.map_number != null && <span>MAP {match.map_number}</span>}
        </div>
        <div className="review-versus">
          <TeamName team={match.team_a.name} winner={winnerA} winnerTitle={translate("reviewWinnerTitle", locale)} />
          <span className="review-vs">VS</span>
          <TeamName team={match.team_b.name} winner={winnerB} winnerTitle={translate("reviewWinnerTitle", locale)} />
        </div>
      </div>

      <div className="review-match-grid">
        <div className="review-cell rosh-cell">
          <span className="review-cell-label">R.O.S.H.</span>
          {match.rosh ? (
            <>
              <div className="rosh-reference-line">
                <RoshScore label={translate("pure", locale)} edge={match.rosh.reference?.pure ?? null} match={match} />
                <RoshScore label={translate("playerAdjusted", locale)} edge={match.rosh.reference?.adjusted ?? null} match={match} />
              </div>
              <div className="rosh-timeline">
                {match.rosh.points.map((point) => (
                  <span key={point.minute}>{point.minute}m <b>{edgeShort(point.adjusted, match)}</b></span>
                ))}
              </div>
            </>
          ) : <span className="review-muted">{translate("reviewNoAuditableDraft", locale)}</span>}
        </div>

        <div className="review-cell result-cell">
          <span className="review-cell-label">{translate("winner", locale)}</span>
          <strong className="winner-name">🏆 {winner?.name ?? "—"}</strong>
          <small>{translate("reviewFinalMapResult", locale)}</small>
        </div>

        <div className="review-cell ai-cell">
          <span className="review-cell-label">{translate("reviewAiDecisions", locale)}</span>
          <div className="review-ai-list">
            {match.ai.map((item) => <AiBadge key={`${item.provider}:${item.model}`} item={item} match={match} locale={locale} />)}
            {match.ai.length === 0 && <span className="review-muted">—</span>}
          </div>
        </div>

        <div className="review-cell odds-cell">
          <span className="review-cell-label">{translate("reviewOddsMovement", locale)}</span>
          {match.odds ? (
            <>
              <div className="odds-team-line"><span>{match.team_a.name}</span><strong>{match.odds.start.odds_a.toFixed(2)} → {match.odds.end.odds_a.toFixed(2)}</strong></div>
              <div className="odds-team-line"><span>{match.team_b.name}</span><strong>{match.odds.start.odds_b.toFixed(2)} → {match.odds.end.odds_b.toFixed(2)}</strong></div>
              <div className="odds-delta">A fair p {signedPp(match.odds.team_a_fair_probability_change_pp)} · {match.odds.end_kind === "CLOSING" ? translate("reviewClosing", locale) : translate("reviewLastDecision", locale)}</div>
            </>
          ) : <span className="review-muted">{translate("reviewNoValidOdds", locale)}</span>}
        </div>
      </div>
    </article>
  );
}

function TeamName({ team, winner, winnerTitle }: { team: string; winner: boolean; winnerTitle: string }) {
  return <strong className={winner ? "review-team winner" : "review-team"}>{team}{winner && <span className="winner-trophy" title={winnerTitle}>🏆</span>}</strong>;
}

function RoshScore({ label, edge, match }: { label: string; edge: ReviewRoshEdge | null; match: ReviewMatch }) {
  if (!edge || edge.edge_pp == null) return <div><span>{label}</span><strong>—</strong></div>;
  const team = edge.favored_team_id === match.team_a.id ? match.team_a.name : edge.favored_team_id === match.team_b.id ? match.team_b.name : "EVEN";
  return <div className={edge.correct === true ? "correct" : edge.correct === false ? "wrong" : "neutral"}><span>{label}</span><strong>{team} {edge.favored_team_id ? `+${Math.abs(edge.edge_pp).toFixed(1)}pp` : "≈0"} {edge.correct === true ? "✓" : edge.correct === false ? "✕" : ""}</strong></div>;
}

function AiBadge({ item, match, locale }: { item: ReviewAiGroup; match: ReviewMatch; locale: Locale }) {
  const action = item.latest?.action ?? "—";
  const actionTeam = action === "BUY_A" ? match.team_a.name : action === "BUY_B" ? match.team_b.name : null;
  const actionLabel = predictionActionLabel(action, locale);
  return (
    <div className="review-ai-badge">
      <div><strong>{providerLabel(item.provider)}</strong><span>{actionTeam ? `${actionLabel} · ${actionTeam}` : actionLabel}</span></div>
      <small>{item.settled_buy_decisions > 0 ? `${item.correct_buy_decisions}/${item.settled_buy_decisions} ${translate("reviewCorrect", locale)}` : translate("reviewNoSettledBuy", locale)}{item.latest?.confidence != null ? ` · conf ${rate(item.latest.confidence, locale)}` : ""}</small>
    </div>
  );
}

function predictionActionLabel(action: string, locale: Locale): string {
  const labels: Record<string, [string, string]> = {
    BUY_A: ["PREDICT A", "预测 A"],
    BUY_B: ["PREDICT B", "预测 B"],
    NO_BUY: ["NO PREDICTION", "暂不预测"],
    INSUFFICIENT_DATA: ["INSUFFICIENT DATA", "数据不足"]
  };
  const pair = labels[action] ?? [action.replaceAll("_", " "), action.replaceAll("_", " ")];
  return locale === "zh-CN" ? pair[1] : pair[0];
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

function accuracyLabel(correct: number, evaluated: number, locale: Locale): string {
  return evaluated ? `${correct}/${evaluated}` : translate("reviewNA", locale);
}
function rate(value: number | null, locale: Locale): string {
  return value == null ? "—" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}
function decimal(value: number | null, digits: number): string { return value == null ? "—" : value.toFixed(digits); }
function signedPp(value: number | null): string { return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(1)}pp`; }
function tone(value: number | null): string { return value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : ""; }
function formatDate(value: string, locale: Locale): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}
