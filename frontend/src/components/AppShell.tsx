import React, { useState } from "react";
import type { JobSummary, MapDetail, MapSummary, RuntimeSnapshot } from "../api";
import { TopBar } from "./TopBar";
import { MatchRail, type MatchCategory } from "./MatchRail";
import { MatchHeader } from "./MatchHeader";
import { DecisionTrustBanner } from "./DecisionTrustBanner";
import { AiDecisionStrip } from "./AiDecisionStrip";
import { MarketCard } from "./MarketCard";
import { DraftAdvantageCard } from "./DraftAdvantageCard";
import { LiveStateCard } from "./LiveStateCard";
import { LineupCard } from "./LineupCard";
import { HistoricalSummaryCard } from "./HistoricalSummaryCard";
import { EvaluationCard } from "./EvaluationCard";
import { DiagnosticsDrawer } from "./DiagnosticsDrawer";
import { useI18n } from "../i18n";

export type NavTab = "OVERVIEW" | "DRAFT" | "LIVE" | "HISTORICAL" | "EVALUATION" | "DIAGNOSTICS";

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

export const AppShell: React.FC<AppShellProps> = ({
  runtime,
  jobs,
  matches,
  selectedMatch,
  detail,
  selectedMapId,
  onSelectMatch,
  onRefresh
}) => {
  const { t } = useI18n();
  const [category, setCategory] = useState<MatchCategory>("ALL");
  const [activeTab, setActiveTab] = useState<NavTab>("OVERVIEW");
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(false);

  const activeMatch = detail || selectedMatch;

  return (
    <div className="dota-app-shell">
      <TopBar
        runtime={runtime}
        onOpenDiagnostics={() => setIsDiagnosticsOpen(true)}
        onRefresh={onRefresh}
      />

      <div className="shell-body">
        {/* Left Match Rail */}
        <MatchRail
          matches={matches}
          selectedId={selectedMapId}
          category={category}
          onSelectCategory={setCategory}
          onSelectMatch={onSelectMatch}
        />

        {/* Main Workspace */}
        <main className="main-workspace">
          {activeMatch ? (
            <div className="match-workspace-content">
              {/* Match Hero Header */}
              <MatchHeader match={activeMatch} />

              {/* Decision Trust Banner */}
              <DecisionTrustBanner match={activeMatch} />

              {/* Primary AI Decision Strip */}
              <AiDecisionStrip decisions={activeMatch.decisions || []} />

              {/* Secondary Navigation Tabs */}
              <div className="secondary-nav-bar">
                <button
                  className={`nav-tab-btn ${activeTab === "OVERVIEW" ? "active" : ""}`}
                  onClick={() => setActiveTab("OVERVIEW")}
                >
                  <span className="tab-icon">❖</span> {t("matchOverview")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "DRAFT" ? "active" : ""}`}
                  onClick={() => setActiveTab("DRAFT")}
                >
                  <span className="tab-icon">⚔</span> {t("draftIntelligence")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "LIVE" ? "active" : ""}`}
                  onClick={() => setActiveTab("LIVE")}
                >
                  <span className="tab-icon">📡</span> {t("liveState")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "HISTORICAL" ? "active" : ""}`}
                  onClick={() => setActiveTab("HISTORICAL")}
                >
                  <span className="tab-icon">📜</span> {t("historical")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "EVALUATION" ? "active" : ""}`}
                  onClick={() => setActiveTab("EVALUATION")}
                >
                  <span className="tab-icon">📊</span> {t("evaluation")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "DIAGNOSTICS" ? "active" : ""}`}
                  onClick={() => setActiveTab("DIAGNOSTICS")}
                >
                  <span className="tab-icon">⚙</span> DIAGNOSTICS
                </button>
              </div>

              {/* Tab Views Content */}
              {activeTab === "OVERVIEW" && (
                <div className="tab-pane overview-pane">
                  {/* Market + Draft Advantage + Live State Row */}
                  <div className="three-col-cards-row">
                    <MarketCard match={activeMatch} />
                    <DraftAdvantageCard
                      match={activeMatch}
                      onViewDetails={() => setActiveTab("DRAFT")}
                    />
                    <LiveStateCard match={activeMatch} />
                  </div>

                  {/* 5v5 Lineup Card */}
                  <LineupCard match={activeMatch} />

                  {/* Historical & Evaluation 2-Col Row */}
                  <div className="two-col-cards-row">
                    <HistoricalSummaryCard match={activeMatch} />
                    <EvaluationCard match={activeMatch} />
                  </div>
                </div>
              )}

              {activeTab === "DRAFT" && (
                <div className="tab-pane draft-pane">
                  <DraftAdvantageCard match={activeMatch} />
                  <LineupCard match={activeMatch} />
                </div>
              )}

              {activeTab === "LIVE" && (
                <div className="tab-pane live-pane">
                  <LiveStateCard match={activeMatch} />
                </div>
              )}

              {activeTab === "HISTORICAL" && (
                <div className="tab-pane historical-pane">
                  <HistoricalSummaryCard match={activeMatch} />
                </div>
              )}

              {activeTab === "EVALUATION" && (
                <div className="tab-pane evaluation-pane">
                  <EvaluationCard match={activeMatch} />
                </div>
              )}

              {activeTab === "DIAGNOSTICS" && (
                <div className="tab-pane diagnostics-pane">
                  <div className="card-header">
                    <span className="card-title">ENGINEERING SYSTEM DIAGNOSTICS</span>
                  </div>
                  <div className="pane-content-box">
                    <button
                      className="primary-action-btn"
                      onClick={() => setIsDiagnosticsOpen(true)}
                    >
                      Open Sliding Diagnostics Drawer ↗
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="empty-workspace-state">
              <div className="empty-icon">❖</div>
              <h2>{t("noCanonicalMaps")}</h2>
              <p>{t("selectMatchPrompt")}</p>
            </div>
          )}
        </main>
      </div>

      {/* Diagnostics Drawer */}
      <DiagnosticsDrawer
        isOpen={isDiagnosticsOpen}
        onClose={() => setIsDiagnosticsOpen(false)}
        runtime={runtime}
        jobs={jobs}
        match={activeMatch}
      />
    </div>
  );
};
