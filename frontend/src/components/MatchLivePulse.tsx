import React from "react";
import type { LiveObservation, MapDetail, MapSummary } from "../api";
import { resolveDecisionLiveFreshness } from "../utils/liveFreshness";
import { resolveVerifiedMapSides, type VerifiedMapSides } from "../utils/mapSides";

const IntelligenceChart = React.lazy(() => import("../Chart"));

type LiveDisplayState = "normal" | "stale" | "disconnected" | "unsynced" | "unavailable" | "final";

interface MatchLivePulseProps {
  match: MapSummary | MapDetail;
  locale: string;
  liveMaxAgeSeconds?: number;
}

interface LeadView {
  amount: number;
  seriesSide: "A" | "B" | null;
  teamName: string | null;
}

interface TrendChange {
  seconds: number;
  edgeDelta: number;
  teamAKills: number | null;
  teamBKills: number | null;
}

export const MatchLivePulse: React.FC<MatchLivePulseProps> = ({
  match,
  locale,
  liveMaxAgeSeconds = 120
}) => {
  const live = match.live;
  const shouldRender = Boolean(live) || match.phase === "LIVE" || match.phase === "AWAITING_RESULT";
  if (!shouldRender) return null;

  const sides = resolveVerifiedMapSides(match);
  const freshness = resolveDecisionLiveFreshness(match);
  const messageAgeSeconds = finiteNumber(live?.message_age_seconds);
  const effectiveAgeSeconds = finiteNumber(freshness.effectiveAgeSeconds);
  const displayState = resolveDisplayState(
    match,
    Boolean(live),
    freshness.complete,
    messageAgeSeconds,
    effectiveAgeSeconds,
    liveMaxAgeSeconds
  );
  const lead = resolveLead(live?.radiant_nw_lead, sides);
  const timeline = timelinePoints(match, sides);
  const changes = trendChanges(match, sides);
  const firstBlood = firstBloodTeam(live?.first_blood, sides);
  const teamA = match.team_a?.name ?? (locale === "zh-CN" ? "队伍 A" : "Team A");
  const teamB = match.team_b?.name ?? (locale === "zh-CN" ? "队伍 B" : "Team B");
  const stateCopy = displayStateCopy(displayState, locale);

  return (
    <section className={`match-live-pulse is-${displayState}`} aria-labelledby="match-live-title">
      <div className="match-live-heading">
        <div>
          <span className="home-eyebrow">LIVE INTELLIGENCE</span>
          <h2 id="match-live-title">{locale === "zh-CN" ? "比赛进程" : "Match progress"}</h2>
        </div>
        <span className={`match-live-status is-${displayState}`} role="status">{stateCopy.label}</span>
      </div>

      {live ? (
        <div className="match-live-main">
          <div className="match-live-lead">
            <span>{locale === "zh-CN" ? "当前净经济" : "Current net worth"}</span>
            <strong>{leadHeadline(lead, locale)}</strong>
            <b className={lead.seriesSide ? `is-team-${lead.seriesSide.toLowerCase()}` : undefined}>
              {formatLeadAmount(lead.amount, locale)}
            </b>
            {stateCopy.detail ? <p>{stateCopy.detail}</p> : null}
          </div>

          <div className="match-live-chart">
            <span className="match-live-chart-side is-team-a">{teamA}</span>
            <span className="match-live-chart-side is-team-b">{teamB}</span>
            {timeline.length >= 2 ? (
              <React.Suspense fallback={<div className="match-live-chart-loading" />}>
                <IntelligenceChart option={liveChartOption(timeline, locale, teamA, teamB)} />
              </React.Suspense>
            ) : (
              <div className="match-live-chart-empty">
                {locale === "zh-CN" ? "等待形成可比较的局势趋势" : "Waiting for a comparable match trend"}
              </div>
            )}
          </div>

          <div className="match-live-changes">
            {changes.length ? changes.map((change) => (
              <div key={change.seconds}>
                <span>{locale === "zh-CN" ? `近 ${change.seconds / 60} 分钟` : `Last ${change.seconds / 60} min`}</span>
                <strong>{formatTrend(change.edgeDelta, match, locale)}</strong>
                <small>{formatKillChange(change, locale)}</small>
              </div>
            )) : (
              <div className="match-live-change-empty">
                <span>{locale === "zh-CN" ? "近期变化" : "Recent change"}</span>
                <strong>{locale === "zh-CN" ? "数据积累中" : "Collecting data"}</strong>
              </div>
            )}
            {firstBlood ? (
              <div>
                <span>{locale === "zh-CN" ? "一血" : "First blood"}</span>
                <strong>{firstBlood}</strong>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="match-live-unavailable">
          <strong>{locale === "zh-CN" ? "暂未收到可信的比赛进程数据" : "No trusted match-progress data yet"}</strong>
          <span>{locale === "zh-CN" ? "页面会在收到有效局势后自动更新。" : "This view updates automatically when a valid state arrives."}</span>
        </div>
      )}

      <div className="match-live-trust">
        {displayState === "final" ? (
          <>
            <TrustItem label={locale === "zh-CN" ? "数据状态" : "Data state"} value={locale === "zh-CN" ? "已归档" : "Archived"} />
            <TrustItem label={locale === "zh-CN" ? "比赛时间" : "Game time"} value={formatGameClock(live?.game_time_seconds)} />
            <TrustItem label={locale === "zh-CN" ? "市场同步" : "Market sync"} value={locale === "zh-CN" ? "不适用" : "Not applicable"} />
          </>
        ) : (
          <>
            <TrustItem label={locale === "zh-CN" ? "连接更新" : "Connection update"} value={formatAge(messageAgeSeconds, locale)} warning={displayState === "disconnected"} />
            <TrustItem label={locale === "zh-CN" ? "局势变化" : "State change"} value={formatAge(effectiveAgeSeconds, locale)} warning={displayState === "stale" || displayState === "disconnected"} />
            <TrustItem label={locale === "zh-CN" ? "市场同步" : "Market sync"} value={syncLabel(match.sync?.status, locale)} warning={displayState === "unsynced" || displayState === "stale" || displayState === "disconnected"} />
          </>
        )}
      </div>
    </section>
  );
};

const TrustItem: React.FC<{ label: string; value: string; warning?: boolean }> = ({ label, value, warning }) => (
  <div><span>{label}</span><strong className={warning ? "is-warning" : undefined}>{value}</strong></div>
);

function resolveDisplayState(
  match: MapSummary | MapDetail,
  hasLive: boolean,
  complete: boolean | null,
  messageAgeSeconds: number | null,
  effectiveAgeSeconds: number | null,
  maxAgeSeconds: number
): LiveDisplayState {
  if (match.phase === "POSTMATCH") return hasLive ? "final" : "unavailable";
  if (!hasLive || complete === false) return "unavailable";
  if (messageAgeSeconds != null && messageAgeSeconds > maxAgeSeconds) return "disconnected";
  if (effectiveAgeSeconds != null && effectiveAgeSeconds > maxAgeSeconds) return "stale";
  if (match.sync?.status !== "SAFE") return "unsynced";
  return "normal";
}

function displayStateCopy(state: LiveDisplayState, locale: string): { label: string; detail: string | null } {
  const zh = locale === "zh-CN";
  switch (state) {
    case "final": return { label: zh ? "最终观测" : "Final observation", detail: null };
    case "stale": return { label: zh ? "显示最后确认值" : "Last confirmed value", detail: zh ? "局势长时间未变化，当前数值不再标记为实时。" : "The state has not changed recently, so this value is no longer marked live." };
    case "disconnected": return { label: zh ? "连接中断" : "Connection interrupted", detail: zh ? "正在显示连接中断前的最后确认值。" : "Showing the last value confirmed before the connection was interrupted." };
    case "unsynced": return { label: zh ? "市场暂不可比较" : "Market comparison unavailable", detail: zh ? "比赛局势仍可查看，但时间尚未与市场数据安全对齐。" : "Match progress remains visible, but its timing is not safely aligned with market data." };
    case "unavailable": return { label: zh ? "数据暂不可用" : "Data unavailable", detail: null };
    default: return { label: zh ? "数据正常" : "Data healthy", detail: null };
  }
}

function resolveLead(value: number | null | undefined, sides: VerifiedMapSides | null): LeadView {
  if (value == null || !Number.isFinite(value) || !sides) return { amount: Number.NaN, seriesSide: null, teamName: null };
  if (value === 0) return { amount: 0, seriesSide: null, teamName: null };
  const team = value > 0 ? sides.radiant : sides.dire;
  return { amount: Math.abs(value), seriesSide: team.seriesSide, teamName: team.name };
}

function leadHeadline(lead: LeadView, locale: string): string {
  if (!Number.isFinite(lead.amount)) return locale === "zh-CN" ? "阵营归属确认中" : "Side assignment pending";
  if (lead.amount === 0) return locale === "zh-CN" ? "双方经济持平" : "Net worth is even";
  return locale === "zh-CN" ? `${lead.teamName} 领先` : `${lead.teamName} leads`;
}

function formatLeadAmount(value: number, locale: string): string {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  return `+${compactNumber(value, locale)}`;
}

function timelinePoints(match: MapSummary | MapDetail, sides: VerifiedMapSides | null): Array<[number, number]> {
  if (!("live_timeline" in match) || !sides) return [];
  const multiplier = sides.radiant.seriesSide === "A" ? 1 : -1;
  const points = match.live_timeline
    .filter((item) => item.game_time_seconds != null && item.radiant_nw_lead != null)
    .map((item) => [item.game_time_seconds!, item.radiant_nw_lead! * multiplier] as [number, number])
    .sort((left, right) => left[0] - right[0]);
  const currentTime = points.at(-1)?.[0];
  return currentTime == null ? [] : points.filter(([seconds]) => seconds >= currentTime - 600);
}

function trendChanges(match: MapSummary | MapDetail, sides: VerifiedMapSides | null): TrendChange[] {
  if (!("live_timeline" in match) || !sides) return [];
  const points = match.live_timeline
    .filter((item) => item.game_time_seconds != null)
    .sort((left, right) => left.game_time_seconds! - right.game_time_seconds!);
  const current = points.at(-1);
  if (!current || current.game_time_seconds == null || current.radiant_nw_lead == null) return [];
  const multiplier = sides.radiant.seriesSide === "A" ? 1 : -1;
  const result: TrendChange[] = [];
  for (const seconds of [180, 300]) {
    const target = current.game_time_seconds - seconds;
    const baseline = nearestGameTime(points, target);
    const tolerance = Math.min(90, Math.max(20, seconds * 0.25));
    if (baseline?.game_time_seconds == null || Math.abs(baseline.game_time_seconds - target) > tolerance || baseline.radiant_nw_lead == null) continue;
    const radiantKills = killDelta(current.radiant_kills, baseline.radiant_kills);
    const direKills = killDelta(current.dire_kills, baseline.dire_kills);
    result.push({
      seconds,
      edgeDelta: (current.radiant_nw_lead - baseline.radiant_nw_lead) * multiplier,
      teamAKills: multiplier === 1 ? radiantKills : direKills,
      teamBKills: multiplier === 1 ? direKills : radiantKills
    });
  }
  return result;
}

function nearestGameTime(points: LiveObservation[], target: number): LiveObservation | null {
  return points.reduce<LiveObservation | null>((best, item) => {
    if (item.game_time_seconds == null) return best;
    if (best?.game_time_seconds == null) return item;
    return Math.abs(item.game_time_seconds - target) < Math.abs(best.game_time_seconds - target) ? item : best;
  }, null);
}

function killDelta(current: number | null, baseline: number | null): number | null {
  if (current == null || baseline == null) return null;
  return Math.max(0, current - baseline);
}

function formatTrend(edgeDelta: number, match: MapSummary | MapDetail, locale: string): string {
  if (Math.abs(edgeDelta) < 1) return locale === "zh-CN" ? "基本持平" : "Mostly even";
  const team = edgeDelta > 0 ? match.team_a?.name : match.team_b?.name;
  const fallback = edgeDelta > 0 ? (locale === "zh-CN" ? "队伍 A" : "Team A") : (locale === "zh-CN" ? "队伍 B" : "Team B");
  return `${team ?? fallback} +${compactNumber(Math.abs(edgeDelta), locale)}`;
}

function formatKillChange(change: TrendChange, locale: string): string {
  if (change.teamAKills == null || change.teamBKills == null) return locale === "zh-CN" ? "击杀变化未知" : "Kill change unavailable";
  return locale === "zh-CN" ? `新增击杀 ${change.teamAKills} : ${change.teamBKills}` : `Kills ${change.teamAKills} : ${change.teamBKills}`;
}

function firstBloodTeam(value: string | null | undefined, sides: VerifiedMapSides | null): string | null {
  if (!value || !sides) return null;
  const normalized = value.toLowerCase();
  if (normalized.includes("radiant")) return sides.radiant.name;
  if (normalized.includes("dire")) return sides.dire.name;
  return null;
}

function liveChartOption(points: Array<[number, number]>, locale: string, teamA: string, teamB: string): object {
  return {
    backgroundColor: "transparent",
    animation: false,
    grid: { top: 18, right: 14, bottom: 28, left: 44 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(6, 14, 22, 0.96)",
      borderColor: "rgba(130, 164, 186, 0.24)",
      textStyle: { color: "#dce7ed", fontSize: 11 },
      formatter: (params: Array<{ value: [number, number] }>) => {
        const value = params[0]?.value;
        if (!value) return "";
        const team = value[1] >= 0 ? teamA : teamB;
        return `${formatGameClock(value[0])}<br/>${team} +${compactNumber(Math.abs(value[1]), locale)}`;
      }
    },
    xAxis: {
      type: "value",
      min: points[0]?.[0],
      max: points.at(-1)?.[0],
      axisLine: { lineStyle: { color: "rgba(119, 146, 166, 0.18)" } },
      axisTick: { show: false },
      axisLabel: { color: "#647b8d", fontSize: 9, formatter: (value: number) => formatGameClock(value) },
      splitLine: { show: false }
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: "#647b8d", fontSize: 9, formatter: (value: number) => value === 0 ? "0" : compactNumber(Math.abs(value), locale) },
      splitLine: { lineStyle: { color: "rgba(119, 146, 166, 0.09)" } }
    },
    series: [{
      type: "line",
      data: points,
      showSymbol: false,
      smooth: 0.22,
      lineStyle: { width: 2.5, color: "#59cbd1" },
      areaStyle: { color: "rgba(78, 190, 198, 0.08)" },
      markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "rgba(168, 187, 199, 0.22)", width: 1 }, data: [{ yAxis: 0 }] }
    }]
  };
}

function syncLabel(status: string | undefined, locale: string): string {
  if (status === "SAFE") return locale === "zh-CN" ? "安全" : "Safe";
  if (!status || status === "UNKNOWN") return locale === "zh-CN" ? "等待确认" : "Pending";
  return locale === "zh-CN" ? "时间未对齐" : "Timing not aligned";
}

function formatAge(value: number | null, locale: string): string {
  if (value == null) return "—";
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return locale === "zh-CN" ? `${seconds} 秒前` : `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return locale === "zh-CN" ? `${minutes} 分 ${remainder} 秒前` : `${minutes}m ${remainder}s ago`;
}

function formatGameClock(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const seconds = Math.max(0, Math.floor(value));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function compactNumber(value: number, locale: string): string {
  if (Math.abs(value) >= 1000) {
    const scaled = value / 1000;
    return `${scaled.toFixed(Math.abs(scaled) >= 10 || Number.isInteger(scaled) ? 0 : 1)}k`;
  }
  return new Intl.NumberFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    maximumFractionDigits: 0
  }).format(value);
}

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
