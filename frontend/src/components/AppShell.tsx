import React, { useState } from "react";
import type { JobSummary, MapDetail, MapSummary, RuntimeSnapshot } from "../api";
import { TopBar } from "./TopBar";
import { PlayerMatchRail } from "./PlayerMatchRail";
import { PlayerMatchHeader } from "./PlayerMatchHeader";
import { DecisionStatusBanner } from "./DecisionStatusBanner";
import { PlayerAiDecisionStrip } from "./PlayerAiDecisionStrip";
import { CanonicalMarketCard } from "./CanonicalMarketCard";
import { PlayerDraftAdvantageCard } from "./PlayerDraftAdvantageCard";
import { LiveStateCard } from "./LiveStateCard";
import { LineupCard } from "./LineupCard";
import { HistoricalSummaryCard } from "./HistoricalSummaryCard";
import { EvaluationCard } from "./EvaluationCard";
import { DiagnosticsDrawer } from "./DiagnosticsDrawer";
import { useI18n } from "../i18n";

export type NavTab = "OVERVIEW" | "DRAFT" | "HISTORICAL" | "EVALUATION";

interface AppShellProps {
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
  matches: MapSummary[];
  selectedMatch: MapSummary | undefined;
  detail: MapDetail | undefined;
  selectedMapId: string | null;
  onSelectMatch: (id: string) => void;
  onRefresh: () => void;
}

export const AppShell: React.FC<AppShellProps> = ({ runtime, jobs, matches, selectedMatch, detail, selectedMapId, onSelectMatch, onRefresh }) => {
  const { locale, t } = useI18n();
  const [activeTab, setActiveTab] = useState<NavTab>("OVERVIEW");
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(false);
  const mainRef = React.useRef<HTMLElement | null>(null);
  const activeMatch = detail || selectedMatch;
  const pendingIdentity = activeMatch?.identity_status === "PENDING_MAP_IDENTITY";
  const waitingForDetail = Boolean(selectedMatch?.canonical_map_id && !detail);

  // Switching matches resets the detail scroll position so the next match
  // always opens at its header instead of mid-content.
  React.useEffect(() => {
    if (selectedMapId != null && typeof mainRef.current?.scrollTo === "function") {
      mainRef.current.scrollTo({ top: 0 });
    }
  }, [selectedMapId]);

  return (
    <div className="dota-app-shell">
      <TopBar runtime={runtime} onOpenDiagnostics={() => setIsDiagnosticsOpen(true)} onRefresh={onRefresh} />
      <div className="shell-body">
        <PlayerMatchRail matches={matches} selectedId={selectedMapId} onSelectMatch={(id) => { onSelectMatch(id); setActiveTab("OVERVIEW"); }} />
        <main ref={mainRef} className="main-workspace">
          {activeMatch ? (
            <div key={selectedMatch?.id ?? "none"} className="match-workspace-content">
              <PlayerMatchHeader match={activeMatch} onSelectMap={onSelectMatch} />

              {pendingIdentity ? (
                <PendingIdentityView match={activeMatch} locale={locale} />
              ) : waitingForDetail ? (
                <LoadingIntelligence locale={locale} />
              ) : (
                <>
                  <DecisionStatusBanner match={activeMatch} />
                  <PlayerAiDecisionStrip decisions={(activeMatch as MapDetail).checkpoint_decisions ?? activeMatch.decisions ?? []} />

                  <div className="secondary-nav-bar" aria-label={t("mapIntelligenceViews")}>
                    <button className={`nav-tab-btn ${activeTab === "OVERVIEW" ? "active" : ""}`} onClick={() => setActiveTab("OVERVIEW")}>{t("matchOverview")}</button>
                    <button className={`nav-tab-btn ${activeTab === "DRAFT" ? "active" : ""}`} onClick={() => setActiveTab("DRAFT")}>{t("draftIntelligence")}</button>
                    <button className={`nav-tab-btn ${activeTab === "HISTORICAL" ? "active" : ""}`} onClick={() => setActiveTab("HISTORICAL")}>{t("historical")}</button>
                    <button className={`nav-tab-btn ${activeTab === "EVALUATION" ? "active" : ""}`} onClick={() => setActiveTab("EVALUATION")}>{t("evaluation")}</button>
                    <button className="nav-tab-btn diagnostics-entry" onClick={() => setIsDiagnosticsOpen(true)}>Diagnostics</button>
                  </div>

                  {activeTab === "OVERVIEW" && (
                    <div className="tab-pane overview-pane player-overview">
                      <div className="primary-analysis-row">
                        <CanonicalMarketCard match={activeMatch} />
                        <PlayerDraftAdvantageCard match={activeMatch} onViewDetails={() => setActiveTab("DRAFT")} />
                      </div>
                      <LineupCard match={activeMatch} />
                      <div className="secondary-analysis-row">
                        <LiveStateCard match={activeMatch} liveMaxAgeSeconds={runtime?.live_state_max_age_seconds} />
                        <HistoricalSummaryCard match={activeMatch} />
                      </div>
                    </div>
                  )}

                  {activeTab === "DRAFT" && <div className="tab-pane draft-pane player-detail-pane"><PlayerDraftAdvantageCard match={activeMatch} /><LineupCard match={activeMatch} /></div>}
                  {activeTab === "HISTORICAL" && <div className="tab-pane historical-pane player-detail-pane"><HistoricalSummaryCard match={activeMatch} /></div>}
                  {activeTab === "EVALUATION" && <div className="tab-pane evaluation-pane player-detail-pane"><EvaluationCard match={activeMatch} /></div>}
                </>
              )}
            </div>
          ) : (
            <div className="empty-workspace-state"><div className="empty-icon">❖</div><h2>{t("noCanonicalMaps")}</h2><p>{t("waitingForProviderDiscovery")}</p></div>
          )}
        </main>
      </div>
      <DiagnosticsDrawer isOpen={isDiagnosticsOpen} onClose={() => setIsDiagnosticsOpen(false)} runtime={runtime} jobs={jobs} match={activeMatch} />
    </div>
  );
};

function LoadingIntelligence({ locale }: { locale: string }) {
  return (
    <section className="analytics-card">
      <div className="empty-rail-msg">
        <strong>{locale === "zh-CN" ? "正在加载比赛情报" : "Loading match intelligence"}</strong>
        <div>{locale === "zh-CN" ? "已选择比赛，正在读取 Draft、AI、Live 与 Historical 详情。" : "Match selected; loading Draft, AI, Live and Historical detail."}</div>
      </div>
    </section>
  );
}

function PendingIdentityView({ match, locale }: { match: MapSummary | MapDetail; locale: string }) {
  return (
    <>
      <div className="trust-banner player-trust-banner trust-degraded">
        <div className="player-trust-icon degraded">!</div>
        <div className="trust-content">
          <span className="trust-title">{locale === "zh-CN" ? "等待本局身份确认" : "Waiting for map identity"}</span>
          <span className="trust-details">{locale === "zh-CN" ? "市场与历史预热继续采集；在 Valve Match ID / Map Identity 确认前不伪造 Draft、Live 或 AI 状态。" : "Market and historical prewarm continue; Draft, Live and AI state are not fabricated before map identity is resolved."}</span>
        </div>
        <div className="trust-pill-group"><span className="trust-pill degraded">PENDING MAP ID</span></div>
      </div>
      <div className="primary-analysis-row">
        <CanonicalMarketCard match={match} />
        <HistoricalSummaryCard match={match} />
      </div>
    </>
  );
}
