import React from "react";
import type { JobSummary, MapDetail, MapSummary, RuntimeSnapshot } from "../api";
import { translateDependency, useI18n } from "../i18n";
import {
  LIVE_BASIC_FIELDS,
  type LiveBasicField,
  resolveDecisionLiveFreshness
} from "../utils/liveFreshness";

interface DiagnosticsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
  match?: MapSummary | MapDetail | null;
}

export const DiagnosticsDrawer: React.FC<DiagnosticsDrawerProps> = ({
  isOpen,
  onClose,
  runtime,
  jobs,
  match
}) => {
  const { locale } = useI18n();

  if (!isOpen) return null;

  const workers = Object.values(runtime?.workers || {});
  const dependencies = Object.values(runtime?.dependencies || {});
  const detail = isMapDetail(match) ? match : undefined;
  const sideIdentity = detail?.snapshot_payload?.identity?.side_identity;
  const liveFieldFreshness = detail ? resolveDecisionLiveFreshness(detail) : null;
  const hasFieldEvidence = liveFieldFreshness?.source === "SNAPSHOT_FIELD_EVIDENCE";

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title-group">
            <h3>System Diagnostics & Engineering Audit</h3>
            <span className={`status-tag ${runtime?.overall || "UNKNOWN"}`}>
              {runtime?.overall || "UNKNOWN"}
            </span>
          </div>
          <button className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="drawer-body">
          {match && (
            <div className="drawer-section">
              <h4>Active Match Snapshot</h4>
              <div className="diag-kv-grid">
                <div className="kv-item">
                  <span className="k">Map ID:</span>
                  <span className="v mono">{match.canonical_map_id || match.id}</span>
                </div>
                <div className="kv-item">
                  <span className="k">Snapshot Hash:</span>
                  <span className="v mono">
                    {match.latest_snapshot?.snapshot_hash || "—"}
                  </span>
                </div>
                <div className="kv-item">
                  <span className="k">Metadata Version:</span>
                  <span className="v mono">
                    {match.market?.[0]?.metadata_version || "—"}
                  </span>
                </div>
                <div className="kv-item">
                  <span className="k">Knowledge Cutoff:</span>
                  <span className="v mono">
                    {match.historical_prewarm?.latest_knowledge_cutoff || "—"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {detail && (
            <div className="drawer-section">
              <h4>{locale === "zh-CN" ? "比赛身份与 Live Freshness 审计" : "Map Identity & Live Freshness Audit"}</h4>
              <div className="diag-kv-grid">
                <div className="kv-item">
                  <span className="k">Side Status:</span>
                  <span className="v mono">{sideIdentity?.status || "UNAVAILABLE"}</span>
                </div>
                <div className="kv-item">
                  <span className="k">Radiant:</span>
                  <span className="v mono">
                    {teamLabel(detail, sideIdentity?.radiant_team_id)}
                  </span>
                </div>
                <div className="kv-item">
                  <span className="k">Dire:</span>
                  <span className="v mono">
                    {teamLabel(detail, sideIdentity?.dire_team_id)}
                  </span>
                </div>
                <div className="kv-item">
                  <span className="k">Side Source:</span>
                  <span className="v mono">{sideIdentity?.source || "—"}</span>
                </div>
                <div className="kv-item">
                  <span className="k">Side Confidence:</span>
                  <span className="v mono">
                    {sideIdentity?.confidence != null
                      ? sideIdentity.confidence.toFixed(3)
                      : "—"}
                  </span>
                </div>
                <div className="kv-item">
                  <span className="k">Side Observed At:</span>
                  <span className="v mono">{sideIdentity?.observed_at || "—"}</span>
                </div>
                <div className="kv-item">
                  <span className="k">Side Blocker:</span>
                  <span className="v mono">{sideIdentity?.blocker || "—"}</span>
                </div>
                <div className="kv-item">
                  <span className="k">Live Effective Age:</span>
                  <span className="v mono">
                    {formatAge(liveFieldFreshness?.effectiveAgeSeconds)}
                  </span>
                </div>
                <div className="kv-item">
                  <span className="k">Freshness Source:</span>
                  <span className="v mono">{liveFieldFreshness?.source || "—"}</span>
                </div>
              </div>

              <div className="diag-table-container">
                <table className="diag-table">
                  <thead>
                    <tr>
                      <th>{locale === "zh-CN" ? "LIVE_BASIC 字段" : "LIVE_BASIC Field"}</th>
                      <th>{locale === "zh-CN" ? "字段年龄" : "Field Age"}</th>
                      <th>{locale === "zh-CN" ? "最后明确观测" : "Last Explicit Observation"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hasFieldEvidence && liveFieldFreshness ? (
                      LIVE_BASIC_FIELDS.map((field) => (
                        <tr key={field}>
                          <td className="mono">{liveFieldLabel(field, locale)}</td>
                          <td className="mono">
                            {formatAge(liveFieldFreshness.agesSeconds[field])}
                          </td>
                          <td className="mono">
                            {liveFieldFreshness.observedAt[field] || "—"}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3}>
                          {locale === "zh-CN"
                            ? "最新 Snapshot 尚无字段级 Live freshness 证据"
                            : "Latest snapshot has no field-level live freshness evidence"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {liveFieldFreshness && (
                <div className="mono">
                  {locale === "zh-CN" ? "必需字段完整" : "Required fields complete"}: {liveFieldFreshness.complete === null ? "—" : liveFieldFreshness.complete ? "YES" : "NO"}
                </div>
              )}
            </div>
          )}

          <div className="drawer-section">
            <h4>Subsystem Dependencies ({dependencies.length})</h4>
            <div className="diag-table-container">
              <table className="diag-table">
                <thead>
                  <tr>
                    <th>Dependency</th>
                    <th>Status</th>
                    <th>Age</th>
                    <th>Failures</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {dependencies.length === 0 ? (
                    <tr>
                      <td colSpan={5}>No dependencies tracked</td>
                    </tr>
                  ) : (
                    dependencies.map((dep) => (
                      <tr key={dep.name}>
                        <td className="mono">{translateDependency(dep.name, locale)}</td>
                        <td>
                          <span className={`status-pill ${dep.status.toLowerCase()}`}>
                            {dep.status}
                          </span>
                        </td>
                        <td className="mono">{dep.age_seconds != null ? `${dep.age_seconds}s` : "—"}</td>
                        <td className="mono">{dep.consecutive_failures}</td>
                        <td className="msg-cell">{dep.message || dep.last_error || "OK"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="drawer-section">
            <h4>Worker Processes ({workers.length})</h4>
            <div className="diag-table-container">
              <table className="diag-table">
                <thead>
                  <tr>
                    <th>Worker Name</th>
                    <th>State</th>
                    <th>Restarts</th>
                    <th>Failures</th>
                    <th>Last Message</th>
                  </tr>
                </thead>
                <tbody>
                  {workers.length === 0 ? (
                    <tr>
                      <td colSpan={5}>No worker data available</td>
                    </tr>
                  ) : (
                    workers.map((w) => (
                      <tr key={w.name}>
                        <td className="mono">{w.name}</td>
                        <td>
                          <span className={`status-pill ${w.state.toLowerCase()}`}>
                            {w.state}
                          </span>
                        </td>
                        <td className="mono">{w.restart_count}</td>
                        <td className="mono">{w.consecutive_failures}</td>
                        <td className="mono">{w.last_message_at || "Just now"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {jobs && (
            <div className="drawer-section">
              <h4>Durable Job Queue Summary</h4>
              <div className="job-status-row">
                {Object.entries(jobs.by_status || {}).map(([st, cnt]) => (
                  <div key={st} className="job-stat-card">
                    <span className="count">{cnt}</span>
                    <span className="label">{st}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

function isMapDetail(match: MapSummary | MapDetail | null | undefined): match is MapDetail {
  return Boolean(match && "snapshot_payload" in match);
}

function teamLabel(match: MapDetail, teamId: string | null | undefined): string {
  if (!teamId) return "—";
  if (match.team_a?.id === teamId) return `${match.team_a.name} · TEAM A`;
  if (match.team_b?.id === teamId) return `${match.team_b.name} · TEAM B`;
  return teamId;
}

function formatAge(value: number | null | undefined): string {
  return value != null && Number.isFinite(value) ? `${value.toFixed(1)}s` : "—";
}

function liveFieldLabel(field: LiveBasicField, locale: string): string {
  const labels: Record<LiveBasicField, [string, string]> = {
    game_time_seconds: ["比赛时间", "Game time"],
    radiant_kills: ["天辉击杀", "Radiant kills"],
    dire_kills: ["夜魇击杀", "Dire kills"],
    radiant_nw_lead: ["天辉经济差", "Radiant NW lead"]
  };
  return labels[field][locale === "zh-CN" ? 0 : 1];
}
