import React from "react";
import { translateStatus, useI18n } from "../i18n";
import type { RuntimeSnapshot } from "../api";

interface TopBarProps {
  runtime: RuntimeSnapshot | undefined;
  onOpenDiagnostics: () => void;
  onRefresh: () => void;
  authEnabled: boolean;
  authenticated: boolean;
  onLogin: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  runtime,
  onOpenDiagnostics,
  onRefresh,
  authEnabled,
  authenticated,
  onLogin
}) => {
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
        <a className="review-nav-btn" href="/performance">
          {locale === "zh-CN" ? "AI 表现榜" : "AI Performance"}
        </a>
        <a className="review-nav-btn" href="/review">
          {locale === "zh-CN" ? "比赛复盘" : "Match Review"}
        </a>
        <a className="topbar-subscription-btn" href="/billing">
          <span className="topbar-subscription-mark" aria-hidden="true">✦</span>
          {locale === "zh-CN" ? "订阅 Pro" : "Get Pro"}
        </a>

        {authenticated ? (
          <a className="topbar-account-btn is-authenticated" href="/billing">
            <span className="topbar-account-dot" aria-hidden="true" />
            {locale === "zh-CN" ? "账户" : "Account"}
          </a>
        ) : authEnabled ? (
          <button className="topbar-account-btn" type="button" onClick={onLogin}>
            {locale === "zh-CN" ? "登录" : "Log in"}
          </button>
        ) : (
          <button
            className="topbar-account-btn is-disabled"
            type="button"
            disabled
            title={
              locale === "zh-CN"
                ? "当前运行环境未启用登录。本地开发请使用 start-local-auth.cmd 启动。"
                : "Authentication is disabled in this runtime. Use start-local-auth.cmd for local development."
            }
          >
            {locale === "zh-CN" ? "登录未启用" : "Login off"}
          </button>
        )}

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