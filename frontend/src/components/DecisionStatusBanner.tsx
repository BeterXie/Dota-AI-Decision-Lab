import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { translateStatus, useI18n, type Locale } from "../i18n";
import { getMatchDisplayPhase } from "../utils/presentation";

export function DecisionStatusBanner({ match }: { match: MapSummary | MapDetail }) {
  const { locale, t } = useI18n();
  const blockers = match.latest_snapshot?.quality?.blockers ?? [];
  const warnings = match.latest_snapshot?.quality?.warnings ?? [];
  const mode = match.latest_snapshot?.mode;
  const phase = getMatchDisplayPhase(match);
  const awaiting = phase === "AWAITING_RESULT";
  const postmatch = phase === "POSTMATCH";
  const state = postmatch ? "healthy" : awaiting ? "degraded" : blockers.length ? "blocked" : warnings.length || !mode ? "degraded" : "healthy";
  const title = postmatch
    ? (locale === "zh-CN" ? "赛果已确认，可查看决策评估" : "Result confirmed — evaluation available")
    : awaiting
      ? (locale === "zh-CN" ? "比赛已结束，等待赛果确认" : "Map finished — awaiting result confirmation")
      : state === "blocked"
        ? (locale === "zh-CN" ? "当前无法生成可靠决策" : "Decision unavailable")
        : state === "degraded"
          ? (locale === "zh-CN" ? "决策可用，但存在限制" : "Decision available with limitations")
          : (locale === "zh-CN" ? "决策数据已就绪" : "Decision data ready");
  const detail = postmatch
    ? (locale === "zh-CN" ? "赛后数据不会改写历史决策；可在评估页查看收盘赔率与赛果证据。" : "Postmatch data does not rewrite historical decisions; closing odds and result evidence are available in Evaluation.")
    : awaiting
      ? (locale === "zh-CN" ? "当前决策记录保持不变，赛果确认后继续结算与评估。" : "Current decision records remain unchanged while result confirmation, settlement and evaluation continue.")
      : [...blockers, ...warnings].map((value) => translateDecisionQuality(value, locale)).join(" · ")
        || (locale === "zh-CN" ? "市场、身份与数据质量检查通过" : "Market, identity and data-quality checks passed");
  const pill = postmatch ? (locale === "zh-CN" ? "赛后" : "POSTMATCH") : awaiting ? (locale === "zh-CN" ? "等待赛果" : "AWAITING RESULT") : mode ? translateStatus(mode, locale) : t("noSnapshot");

  return (
    <div className={`trust-banner player-trust-banner trust-${state}`}>
      <div className={`player-trust-icon ${state}`}>{state === "healthy" ? "✓" : state === "degraded" ? "!" : "×"}</div>
      <div className="trust-content"><span className="trust-title">{title}</span><span className="trust-details">{detail}</span></div>
      <div className="trust-pill-group"><span className={`trust-pill ${state}`}>{pill}</span></div>
    </div>
  );
}

const sideQualityMessages: Record<string, Record<Locale, string>> = {
  SIDE_IDENTITY_VALVE_MATCH_MISSING: { en: "Valve match identity is missing", "zh-CN": "缺少 Valve 比赛身份" },
  SIDE_IDENTITY_EVIDENCE_MISSING: { en: "Map-side evidence has not been observed yet", "zh-CN": "尚未观测到本局阵营证据" },
  SIDE_IDENTITY_UNRESOLVED: { en: "Radiant / Dire sides are not verified", "zh-CN": "本局天辉 / 夜魇阵营尚未验证" },
  SIDE_IDENTITY_TEAM_MAPPING_MISSING: { en: "DLTV team mapping is incomplete for map sides", "zh-CN": "本局阵营所需的 DLTV 队伍映射不完整" },
  SIDE_IDENTITY_SERIES_CONFLICT: { en: "Map-side identity conflicts with the canonical series teams", "zh-CN": "本局阵营身份与规范化系列赛队伍冲突" },
  SIDE_IDENTITY_PROVIDER_CONFLICT: { en: "Provider map-side evidence is contradictory", "zh-CN": "Provider 本局阵营证据互相冲突" },
  SIDE_IDENTITY_PARTIAL: { en: "Only part of the map-side identity is available", "zh-CN": "本局阵营身份仅部分可用" },
  ROSTER_SIDE_IDENTITY_UNRESOLVED: { en: "Current roster is not assigned to Team A / B until map sides are verified", "zh-CN": "本局阵营验证前，当前阵容不会绑定到规范化 Team A / B" }
};

function translateDecisionQuality(status: string, locale: Locale): string {
  const normalized = status.replaceAll(" ", "_");
  return sideQualityMessages[normalized]?.[locale] ?? translateStatus(status, locale);
}
