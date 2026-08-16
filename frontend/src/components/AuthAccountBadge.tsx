import React, { useState } from "react";
import { useI18n } from "../i18n";
import type { AuthUser } from "../authApi";

interface AuthAccountBadgeProps {
  user: AuthUser;
  onLogout: () => Promise<void>;
}

export const AuthAccountBadge: React.FC<AuthAccountBadgeProps> = ({ user, onLogout }) => {
  const { locale } = useI18n();
  const [busy, setBusy] = useState(false);
  const label = locale === "zh-CN" ? "退出" : "Sign out";

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
    <div className="auth-account-badge" aria-label={locale === "zh-CN" ? "当前账户" : "Current account"}>
      <span className="auth-account-dot" aria-hidden="true" />
      <span className="auth-account-email" title={user.email}>{user.email}</span>
      <button type="button" disabled={busy} onClick={() => void handleLogout()}>
        {busy ? "…" : label}
      </button>
    </div>
  );
};
