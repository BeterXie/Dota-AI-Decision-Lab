import React from "react";
import type { JobSummary, MapDetail, MapSummary, RuntimeSnapshot } from "../api";
import { translateDependency, useI18n } from "../i18n";

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
  const { locale, t } = useI18n();

  if (!isOpen) return null;

  const workers = Object.values(runtime?.workers || {});
  const dependencies = Object.values(runtime?.dependencies || {});

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
          {/* Snapshot metadata if match is selected */}
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

          {/* Subsystem Dependencies */}
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

          {/* Workers Health */}
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

          {/* Job Queue Status */}
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
