import React, { useState } from "react";
import type { JobSummary, MapDetail, MapSummary, RuntimeSnapshot } from "../api";
import { TopBar } from "./TopBar";
import { PlayerMatchRail } from "./PlayerMatchRail";
import { PlayerMatchHeader } from "./PlayerMatchHeader";
import { DecisionStatusBanner } from "./DecisionStatusBanner";
import { PlayerAiDecisionPanel } from "./PlayerAiDecisionPanel";
import { CanonicalMarketCard } from "./CanonicalMarketCard";
import { PlayerDraftAdvantageCard } from "./PlayerDraftAdvantageCard";
import { LiveStateCard } from "./LiveStateCard";
import { LineupCard } from "./LineupCard";
import { HistoricalSummaryCard } from "./HistoricalSummaryCard";
import { EvaluationCard } from "./EvaluationCard";
import { DiagnosticsDrawer } from "./DiagnosticsDrawer";
import { useI18n } from "../i18n";

export type NavTab = "OVERVIEW" | "DRAFT" | "HISTORICAL" | "EVALUATION";

export interface AiAccessState {
  authEnabled: boolean;
  authenticated: boolean;
  entitled: boolean;
  scope: "GLOBAL" | "EVENT" | "SERIES" | "MAP" | "FREE" | "POSTMATCH" | null;
  loading: boolean;
  upgradeHref: string;
}

interface PublicAiSummary {
  required_entitlement: string;
  analysis_available: boolean;
  updated_at: string | null;
  completed_models: number;
}

interface AppShellProps {
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
  matches: MapSummary[];
  selectedMatch: MapSummary | undefined;
  detail: MapDetail | undefined;
  detailLoading?: boolean;
  detailError?: Error | null;
  selectedMapId: string | null;
  onSelectMatch: (id: string) => void;
  onRefresh: () => void;
  aiAccess: AiAccessState;
  onLogin: () => void;
}

export const AppShell: React.FC<AppShellProps> = ({ runtime, jobs, matches, selectedMatch, detail, detailLoading, detailError, selectedMapId, onSelectMatch, onRefresh, aiAccess, onLogin }) => {
  const { locale, t } = useI18n();
  const [activeTab, setActiveTab] = useState<NavTab>("OVERVIEW");
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(false);
  const mainRef = React.useRef<HTMLElement | null>(null);
  const activeMatch = detail || selectedMatch;
  const pendingIdentity = activeMatch?.identity_status === "PENDING_MAP_IDENTITY";
  const waitingForDetail = Boolean(selectedMatch?.canonical_map_id && detailLoading && !detail);
  const publicAi = (activeMatch as (MapSummary & { ai_access?: PublicAiSummary }) | undefined)?.ai_access;
  const checkpointDecisions = (activeMatch as MapDetail | undefined)?.checkpoint_decisions ?? [];
  const aiDecisions = checkpointDecisions.length > 0 ? checkpointDecisions : activeMatch?.decisions ?? [];

  React.useEffect(() => {
    if (selectedMapId != null && typeof mainRef.current?.scrollTo === "function") {
      mainRef.current.scrollTo({ top: 0 });
    }
  }, [selectedMapId]);

  return (
    <div className="dota-app-shell">
      <TopBar
        runtime={runtime}
        onOpenDiagnostics={() => setIsDiagnosticsOpen(true)}
        onRefresh={onRefresh}
        authEnabled={aiAccess.authEnabled}
        authenticated={aiAccess.authenticated}
        onLogin={onLogin}
      />
      <div className="shell-body">
        <PlayerMatchRail matches={matches} selectedId={selectedMapId} onSelectMatch={(id) => { onSelectMatch(id); setActiveTab("OVERVIEW"); }} />
        <main ref={mainRef} className="main-workspace">
          {activeMatch ? (
            <div key={selectedMatch?.id ?? "none"} className="match-workspace-content">
              <PlayerMatchHeader match={activeMatch} onSelectMap={onSelectMatch} />

              {detailError ? (
                <DetailErrorView error={detailError} locale={locale} />
              ) : pendingIdentity ? (
                <PendingIdentityView match={activeMatch} locale={locale} />
              ) : waitingForDetail ? (
                <LoadingIntelligence locale={locale} />
              ) : (
                <>
                  <DecisionStatusBanner match={activeMatch} />
                  <PlayerAiDecisionPanel
                    decisions={aiDecisions}
                    currentSnapshotId={activeMatch.latest_snapshot?.id}
                    access={aiAccess}
                    analysisAvailable={publicAi?.analysis_available ?? Boolean(activeMatch.latest_snapshot)}
                    completedModels={publicAi?.completed_models ?? 0}
                    onLogin={onLogin}
                  />
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

function DetailErrorView({ error, locale }: { error: Error; locale: string }) {
  return <section className="analytics-card"><div className="empty-rail-msg"><strong>{locale === "zh-CN" ? "比赛情报加载失败" : "Failed to load match intelligence"}</strong><div>{error.message}</div></div></section>;
}

function LoadingIntelligence({ locale }: { locale: string }) {
  return <section className="analytics-card"><div className="empty-rail-msg"><strong>{locale === "zh-CN" ? "正在加载比赛情报" : "Loading match intelligence"}</strong><div>{locale === "zh-CN" ? "已选择比赛，正在读取公开的 Draft、Live 与 Historical 详情。" : "Match selected; loading public Draft, Live and Historical detail."}</div></div></section>;
}

function PendingIdentityView({ match, locale }: { match: MapSummary | MapDetail; locale: string }) {
  return <><div className="trust-banner player-trust-banner trust-degraded"><div className="player-trust-icon degraded">!</div><div className="trust-content"><span className="trust-title">{locale === "zh-CN" ? "等待本局身份确认" : "Waiting for map identity"}</span><span className="trust-details">{locale === "zh-CN" ? "市场与历史预热继续采集；在 Valve Match ID / Map Identity 确认前不伪造 Draft、Live 或 AI 状态。" : "Market and historical prewarm continue; Draft, Live and AI state are not fabricated before identity is resolved."}</span></div><div className="trust-pill-group"><span className="trust-pill degraded">PENDING MAP ID</span></div></div><div className="primary-analysis-row"><CanonicalMarketCard match={match} /><HistoricalSummaryCard match={match} /></div></>;
}
