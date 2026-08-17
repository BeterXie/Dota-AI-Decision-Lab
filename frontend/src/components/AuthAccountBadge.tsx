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

  const handleLogout = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onLogout();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-account-badge" aria-label={t("authCurrentAccount")}>
      <span className="auth-account-dot" aria-hidden="true" />
      <span className="auth-account-email" title={user.email}>{user.email}</span>
      <a href="/notifications">{locale === "zh-CN" ? "通知" : "Notifications"}</a>
      <button type="button" disabled={busy} onClick={() => void handleLogout()}>
        {busy ? "…" : t("authSignOut")}
      </button>
    </div>
  );
};
