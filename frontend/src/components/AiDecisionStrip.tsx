import React, { useState } from "react";
import type { AiDecision } from "../api";
import { useI18n } from "../i18n";

interface AiDecisionStripProps { decisions: AiDecision[]; }

export const AiDecisionStrip: React.FC<AiDecisionStripProps> = ({ decisions }) => {
  const { t } = useI18n();
  const [selectedDecision, setSelectedDecision] = useState<AiDecision | null>(null);
  const modelCards = decisions.map((decisionData) => ({
    decisionData,
    action: decisionData.decision?.action || t("cannotDecide"),
    confidenceMath: decisionData.decision?.confidence == null
      ? null
      : Math.round(decisionData.decision.confidence * 100),
    fairProbAMath: decisionData.decision?.fair_probability_a == null
      ? null
      : Math.round(decisionData.decision.fair_probability_a * 100)
  }));

  // Calculate agreement summary
  const actionsCount: Record<string, number> = {};
  modelCards.forEach((c) => {
    actionsCount[c.action] = (actionsCount[c.action] || 0) + 1;
  });

  const probs = modelCards.flatMap((card) => card.fairProbAMath == null ? [] : [card.fairProbAMath]);
  const minProb = probs.length ? Math.min(...probs) : null;
  const maxProb = probs.length ? Math.max(...probs) : null;
  const spread = minProb == null || maxProb == null ? null : maxProb - minProb;

  return (
    <div className="ai-decision-container">
      <div className="ai-strip-header">
        <div className="section-title-group">
          <h3 className="section-title">AI DECISION</h3>
          <span className="info-icon" title="Aggregated LLM multi-model decision predictions">
            ⓘ
          </span>
        </div>
      </div>

      <div className="ai-strip-layout">
        <div className="ai-cards-grid">
          {modelCards.length === 0 && <div className="empty-rail-msg">{t("noAiDecisions")}</div>}
          {modelCards.map(({ decisionData, action, confidenceMath, fairProbAMath }) => {
            const isBuyA = action === "BUY A";
            const isBuyB = action === "BUY B";
            const isHold = action === "HOLD";
            const isNoBuy = action === "NO BUY";

            const actionClass = isBuyA
              ? "action-buy-a"
              : isBuyB
              ? "action-buy-b"
              : isHold
              ? "action-hold"
              : isNoBuy
              ? "action-nobuy"
              : "action-none";

            return (
              <div
                key={decisionData.id}
                className="ai-model-card"
                onClick={() => setSelectedDecision(decisionData)}
                title="Click to view model reasoning & details"
              >
                <div className="card-model-header">
                  <span className="model-badge-icon">❖</span>
                  <span className="model-name">{decisionData.model}</span>
                </div>

                <div className="card-action-row">
                  <div className={`action-pill ${actionClass}`}>{action}</div>
                </div>

                <div className="card-metrics-row">
                  <div className="metric-col">
                    <span className="metric-val">{fairProbAMath == null ? "—" : `${fairProbAMath}%`}</span>
                    <span className="metric-lbl">Fair Prob</span>
                  </div>
                  <div className="metric-col">
                    <span className="metric-val">{confidenceMath == null ? "—" : `${confidenceMath}%`}</span>
                    <span className="metric-lbl">Confidence</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="ai-agreement-box">
          <div className="agreement-header">AI AGREEMENT</div>
          <div className="agreement-body">
            <div className="direction-list">
              {Object.entries(actionsCount).map(([act, cnt]) => (
                <div key={act} className="direction-item">
                  <span className="dir-count">{cnt}</span>
                  <span className="dir-name">{act}</span>
                </div>
              ))}
            </div>

            <div className="spread-stat-row">
              <div className="stat-col">
                <span className="stat-lbl">Spread</span>
                <span className="stat-val">{spread == null ? "—" : `${spread}pp`}</span>
              </div>
              <div className="stat-col">
                <span className="stat-lbl">Disagreement</span>
                <span className="stat-val highlight">
                  {spread == null ? "—" : spread > 15 ? "High" : spread > 8 ? "Moderate" : "Low"}
                </span>
              </div>
            </div>

            <div className="prob-range-bar">
              <span className="range-lbl">Probability Range</span>
              <span className="range-val">
                {minProb == null ? "—" : `${minProb}% - ${maxProb}%`}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Model details modal */}
      {selectedDecision && (
        <div className="modal-backdrop" onClick={() => setSelectedDecision(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {selectedDecision.provider} ({selectedDecision.model}) Detail
              </h3>
              <button className="close-btn" onClick={() => setSelectedDecision(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div className="detail-section">
                <h4>Primary Reasons</h4>
                <ul>
                  {selectedDecision.decision?.primary_reasons?.map((r, i) => (
                    <li key={i}>{r}</li>
                  )) || <li>{t("notObserved")}</li>}
                </ul>
              </div>

              <div className="detail-section">
                <h4>Counter Arguments</h4>
                <ul>
                  {selectedDecision.decision?.counter_arguments?.map((r, i) => (
                    <li key={i}>{r}</li>
                  )) || <li>{t("notObserved")}</li>}
                </ul>
              </div>

              <div className="detail-section">
                <h4>Data Quality Concerns</h4>
                <ul>
                  {selectedDecision.decision?.data_quality_concerns?.map((r, i) => (
                    <li key={i}>{r}</li>
                  )) || <li>{t("notObserved")}</li>}
                </ul>
              </div>

              <div className="detail-section inline-meta">
                <span>Model Version: {selectedDecision.model_version}</span>
                <span>Prompt Version: {selectedDecision.prompt_version}</span>
                <span>Latency: {selectedDecision.latency_seconds == null ? "—" : `${selectedDecision.latency_seconds}s`}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
