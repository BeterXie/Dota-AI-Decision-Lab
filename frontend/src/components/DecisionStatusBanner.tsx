import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { translateStatus, useI18n } from "../i18n";
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
      : [...blockers, ...warnings].map((value) => translateStatus(value, locale)).join(" · ")
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
