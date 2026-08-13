import React, { useState } from "react";
import type { JobSummary, MapDetail, MapSummary, RuntimeSnapshot } from "../api";
import { TopBar } from "./TopBar";
import { MatchRail } from "./MatchRail";
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
        <MatchRail
          matches={matches}
          selectedId={selectedMapId}
          onSelectMatch={(id) => {
            onSelectMatch(id);
            setActiveTab("OVERVIEW");
          }}
        />

        <main className="main-workspace">
          {activeMatch ? (
            <div className="match-workspace-content">
              <MatchHeader match={activeMatch} />
              <DecisionTrustBanner match={activeMatch} />
              <AiDecisionStrip decisions={activeMatch.decisions || []} />

              <div className="secondary-nav-bar" aria-label={t("mapIntelligenceViews")}>
                <button
                  className={`nav-tab-btn ${activeTab === "OVERVIEW" ? "active" : ""}`}
                  onClick={() => setActiveTab("OVERVIEW")}
                >
                  {t("matchOverview")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "DRAFT" ? "active" : ""}`}
                  onClick={() => setActiveTab("DRAFT")}
                >
                  {t("draftIntelligence")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "HISTORICAL" ? "active" : ""}`}
                  onClick={() => setActiveTab("HISTORICAL")}
                >
                  {t("historical")}
                </button>
                <button
                  className={`nav-tab-btn ${activeTab === "EVALUATION" ? "active" : ""}`}
                  onClick={() => setActiveTab("EVALUATION")}
                >
                  {t("evaluation")}
                </button>
                <button
                  className="nav-tab-btn diagnostics-entry"
                  onClick={() => setIsDiagnosticsOpen(true)}
                >
                  Diagnostics
                </button>
              </div>

              {activeTab === "OVERVIEW" && (
                <div className="tab-pane overview-pane player-overview">
                  <div className="primary-analysis-row">
                    <MarketCard match={activeMatch} />
                    <DraftAdvantageCard
                      match={activeMatch}
                      onViewDetails={() => setActiveTab("DRAFT")}
                    />
                  </div>

                  <LineupCard match={activeMatch} />

                  <div className="secondary-analysis-row">
                    <LiveStateCard match={activeMatch} />
                    <HistoricalSummaryCard match={activeMatch} />
                  </div>
                </div>
              )}

              {activeTab === "DRAFT" && (
                <div className="tab-pane draft-pane player-detail-pane">
                  <DraftAdvantageCard match={activeMatch} />
                  <LineupCard match={activeMatch} />
                </div>
              )}

              {activeTab === "HISTORICAL" && (
                <div className="tab-pane historical-pane player-detail-pane">
                  <HistoricalSummaryCard match={activeMatch} />
                </div>
              )}

              {activeTab === "EVALUATION" && (
                <div className="tab-pane evaluation-pane player-detail-pane">
                  <EvaluationCard match={activeMatch} />
                </div>
              )}
            </div>
          ) : (
            <div className="empty-workspace-state">
              <div className="empty-icon">❖</div>
              <h2>{t("noCanonicalMaps")}</h2>
              <p>{t("waitingForProviderDiscovery")}</p>
            </div>
          )}
        </main>
      </div>

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
