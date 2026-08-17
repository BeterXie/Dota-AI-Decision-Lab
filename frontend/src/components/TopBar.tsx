import React from "react";
import { translateStatus, useI18n } from "../i18n";
import type { RuntimeSnapshot } from "../api";
import { logout } from "../authApi";

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
  const [logoutBusy, setLogoutBusy] = React.useState(false);
  const [logoutError, setLogoutError] = React.useState<string | null>(null);
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

  const handleLogout = async () => {
    if (logoutBusy) return;
    setLogoutBusy(true);
    setLogoutError(null);
    try {
      await logout();
      // Logout revokes the server-side session and clears the HttpOnly cookie.
      // A full navigation guarantees every React Query cache and protected route
      // is rebuilt from the now-anonymous /api/auth/session response.
      window.location.assign("/");
    } catch {
      setLogoutError(locale === "zh-CN" ? "退出失败，请重试" : "Sign out failed. Try again.");
      setLogoutBusy(false);
    }
  };

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
          <div className="topbar-account-actions">
            <a className="topbar-account-btn is-authenticated" href="/billing">
              <span className="topbar-account-dot" aria-hidden="true" />
              {locale === "zh-CN" ? "账户" : "Account"}
            </a>
            <button
              className="topbar-logout-btn"
              type="button"
              disabled={logoutBusy}
              onClick={() => void handleLogout()}
            >
              {logoutBusy ? "…" : locale === "zh-CN" ? "退出" : "Sign out"}
            </button>
            {logoutError && (
              <span className="topbar-logout-error" role="alert">
                {logoutError}
              </span>
            )}
          </div>
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