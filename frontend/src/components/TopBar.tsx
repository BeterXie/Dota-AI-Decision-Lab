import React from "react";
import { Renew } from "@carbon/icons-react";
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
          <Renew size={18} />
        </button>
      </div>
    </header>
  );
};
