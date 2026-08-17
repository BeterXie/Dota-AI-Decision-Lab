import React, { useState } from "react";
import type { AuthUser } from "../authApi";
import { useI18n } from "../i18n";

interface AuthAccountBadgeProps {
  user: AuthUser;
  onLogout: () => Promise<void>;
}

export const AuthAccountBadge: React.FC<AuthAccountBadgeProps> = ({ user, onLogout }) => {
  const { locale, t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogout = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onLogout();
      // The server revokes the session and clears the HttpOnly cookie. Reload the
      // document so every auth/query observer is rebuilt from the anonymous
      // /api/auth/session response instead of retaining a stale signed-in view.
      window.location.reload();
    } catch {
      setError(locale === "zh-CN" ? "退出失败，请重试" : "Sign out failed. Try again.");
      setBusy(false);
    }
  };

  return (
    <div className="auth-account-badge" aria-label={t("authCurrentAccount")}>
      <span className="auth-account-dot" aria-hidden="true" />
      <span className="auth-account-email" title={user.email}>{user.email}</span>
      <a href="/billing">{locale === "zh-CN" ? "Pro" : "Pro"}</a>
      <a href="/notifications">{locale === "zh-CN" ? "通知" : "Notifications"}</a>
      <button type="button" disabled={busy} onClick={() => void handleLogout()}>
        {busy ? "…" : t("authSignOut")}
      </button>
      {error && <span className="auth-account-error" role="alert">{error}</span>}
    </div>
  );
};
