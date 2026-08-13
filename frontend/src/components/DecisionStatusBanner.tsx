import React from "react";
import type { MapDetail, MapSummary } from "../api";
import { translateStatus, useI18n } from "../i18n";

export function DecisionStatusBanner({ match }: { match: MapSummary | MapDetail }) {
  const { locale, t } = useI18n();
  const blockers = match.latest_snapshot?.quality?.blockers ?? [];
  const warnings = match.latest_snapshot?.quality?.warnings ?? [];
  const mode = match.latest_snapshot?.mode;
  const state = blockers.length ? "blocked" : warnings.length || !mode ? "degraded" : "healthy";
  const title = state === "blocked"
    ? (locale === "zh-CN" ? "当前无法生成可靠决策" : "Decision unavailable")
    : state === "degraded"
      ? (locale === "zh-CN" ? "决策可用，但存在限制" : "Decision available with limitations")
      : (locale === "zh-CN" ? "决策数据已就绪" : "Decision data ready");
  const detail = [...blockers, ...warnings].map((value) => translateStatus(value, locale)).join(" · ")
    || (locale === "zh-CN" ? "市场、身份与数据质量检查通过" : "Market, identity and data-quality checks passed");

  return (
    <div className={`trust-banner player-trust-banner trust-${state}`}>
      <div className={`player-trust-icon ${state}`}>{state === "healthy" ? "✓" : state === "degraded" ? "!" : "×"}</div>
      <div className="trust-content"><span className="trust-title">{title}</span><span className="trust-details">{detail}</span></div>
      <div className="trust-pill-group"><span className={`trust-pill ${state}`}>{mode ? translateStatus(mode, locale) : t("noSnapshot")}</span></div>
    </div>
  );
}
