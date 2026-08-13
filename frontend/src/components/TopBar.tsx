import React from "react";
import { translateStatus, useI18n } from "../i18n";
import type { RuntimeSnapshot } from "../api";

interface TopBarProps {
  runtime: RuntimeSnapshot | undefined;
  onOpenDiagnostics: () => void;
  onRefresh: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({ runtime, onOpenDiagnostics, onRefresh }) => {
  const { locale, setLocale, t } = useI18n();
  const status = runtime?.overall ?? "UNKNOWN";
  const statusText = translateStatus(status, locale);

  const statusClass =
    status === "READY"
      ? "status-ready"
      : status === "DEGRADED"
      ? "status-degraded"
      : status === "ACTION_REQUIRED"
      ? "status-error"
      : "status-unknown";

  return (
    <header className="top-bar">
      <div className="top-bar-left">
        <div className="app-logo">
          <span className="logo-icon">❖</span>
          <span className="logo-text">Dota AI Decision Lab</span>
        </div>
      </div>

      <div className="top-bar-right">
        <button
          className={`system-status-btn ${statusClass}`}
          onClick={onOpenDiagnostics}
          title="Open Engineering Diagnostics"
        >
          <span className="status-dot">●</span>
          <span className="status-label">System {statusText}</span>
        </button>

        <div className="lang-switcher">
          <button
            className={`lang-btn ${locale === "zh-CN" ? "active" : ""}`}
            onClick={() => setLocale("zh-CN")}
            aria-pressed={locale === "zh-CN"}
          >
            中文
          </button>
          <button
            className={`lang-btn ${locale === "en" ? "active" : ""}`}
            onClick={() => setLocale("en")}
            aria-pressed={locale === "en"}
          >
            EN
          </button>
        </div>

        <button className="icon-btn" onClick={onRefresh} title={t("refreshData")}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M20 6v5h-5M4 18v-5h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M18.3 9A7 7 0 0 0 6.5 6.2L4 8M5.7 15A7 7 0 0 0 17.5 17.8L20 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </header>
  );
};
