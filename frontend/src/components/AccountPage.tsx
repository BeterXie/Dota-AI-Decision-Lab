import React from "react";
import type { AuthSessionState } from "../authApi";
import { useI18n } from "../i18n";

const NOTIFICATION_ENTITLEMENT = "realtime_notifications";

export function AccountPage({
  session,
  authLoading,
  onLogin,
  onLogout
}: {
  session: AuthSessionState | undefined;
  authLoading: boolean;
  onLogin: () => void;
  onLogout: () => Promise<void>;
}) {
  const { locale, setLocale } = useI18n();
  const [logoutBusy, setLogoutBusy] = React.useState(false);
  const [logoutError, setLogoutError] = React.useState<string | null>(null);
  const zh = locale === "zh-CN";
  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);

  if (authLoading) {
    return (
      <section className="account-v2-state" aria-live="polite">
        <span aria-hidden="true" />
        <strong>{zh ? "正在读取账户信息…" : "Loading account…"}</strong>
      </section>
    );
  }

  if (session?.enabled === false) {
    return (
      <section className="account-v2-gate product-container">
        <div className="account-v2-gate-card">
          <span className="home-eyebrow">ACCOUNT</span>
          <h1>{zh ? "当前环境没有启用登录" : "Sign-in is disabled in this environment"}</h1>
          <p>{zh ? "公开赛事和比赛仍然可以正常浏览。账户、会员和通知设置会在启用登录后开放。" : "Public events and matches are still available. Account, membership and notification settings become available when authentication is enabled."}</p>
          <a className="product-btn product-btn-secondary" href="/events">{zh ? "浏览赛事" : "Browse events"}</a>
        </div>
      </section>
    );
  }

  if (!signedIn || !session?.user) {
    return (
      <section className="account-v2-gate product-container">
        <div className="account-v2-gate-card">
          <span className="home-eyebrow">ACCOUNT</span>
          <h1>{zh ? "登录后管理你的账户" : "Sign in to manage your account"}</h1>
          <p>{zh ? "登录后可以查看会员状态、赛事 Pass、通知设置和语言偏好。" : "Sign in to view membership, event passes, notifications and language preferences."}</p>
          <button className="product-btn product-btn-primary" type="button" onClick={onLogin}>{zh ? "登录" : "Sign in"}<span>→</span></button>
        </div>
      </section>
    );
  }

  const user = session.user;
  const label = user.display_name || user.email || (zh ? "Steam 用户" : "Steam user");
  const hasGlobalNotifications = session.entitlements.includes(NOTIFICATION_ENTITLEMENT);
  const scopedGrants = session.grants.filter((grant) => grant.scope_type !== "GLOBAL");
  const activeNotificationAccess = hasGlobalNotifications || session.grants.some(
    (grant) => grant.entitlement === NOTIFICATION_ENTITLEMENT
  );
  const avatarLetter = label.slice(0, 1).toUpperCase();

  const signOut = async () => {
    if (logoutBusy) return;
    setLogoutBusy(true);
    setLogoutError(null);
    try {
      await onLogout();
      window.location.assign("/");
    } catch {
      setLogoutError(zh ? "退出失败，请重试。" : "Sign out failed. Try again.");
      setLogoutBusy(false);
    }
  };

  return (
    <div className="account-v2 product-container">
      <header className="account-v2-header">
        <div>
          <span className="home-eyebrow">ACCOUNT</span>
          <h1>{zh ? "账户" : "Account"}</h1>
          <p>{zh ? "管理登录信息、语言、会员和通知。" : "Manage your sign-in details, language, membership and notifications."}</p>
        </div>
      </header>

      <section className="account-v2-profile-card">
        <div className="account-v2-avatar" aria-hidden="true">
          {user.avatar_url ? <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" /> : avatarLetter}
        </div>
        <div className="account-v2-profile-copy">
          <strong>{label}</strong>
          <span>{user.email || (zh ? "尚未绑定邮箱" : "No email linked")}</span>
        </div>
        <span className="account-v2-plan">FREE</span>
      </section>

      <div className="account-v2-grid">
        <section className="account-v2-card">
          <div className="account-v2-card-heading">
            <div><span aria-hidden="true">◎</span><div><h2>{zh ? "账号信息" : "Account details"}</h2><p>{zh ? "当前用于识别这个账户的信息。" : "The information currently used to identify this account."}</p></div></div>
          </div>
          <dl className="account-v2-details">
            <div><dt>{zh ? "登录邮箱" : "Email"}</dt><dd>{user.email || (zh ? "未绑定" : "Not linked")}</dd></div>
            <div><dt>{zh ? "邮箱状态" : "Email status"}</dt><dd>{user.email ? (user.email_verified_at ? (zh ? "已验证" : "Verified") : (zh ? "未验证" : "Not verified")) : "—"}</dd></div>
            <div><dt>{zh ? "加入时间" : "Joined"}</dt><dd>{formatDate(user.created_at, locale)}</dd></div>
          </dl>
          {!user.email && <p className="account-v2-note">{zh ? "Steam 登录可以不绑定邮箱；需要邮件通知时再绑定即可。" : "Steam sign-in can work without an email. Link one later if you want email notifications."}</p>}
        </section>

        <section className="account-v2-card">
          <div className="account-v2-card-heading">
            <div><span aria-hidden="true">✦</span><div><h2>{zh ? "会员与比赛权限" : "Membership & match access"}</h2><p>{zh ? "Free、赛事 Pass 和系列赛 Pass 分开显示。" : "Free access, Event Pass and Series Pass are shown separately."}</p></div></div>
          </div>
          <div className="account-v2-membership-row"><span>{zh ? "当前方案" : "Current plan"}</span><strong>{zh ? "免费" : "Free"}</strong></div>
          <div className="account-v2-membership-row"><span>{zh ? "赛事 / 系列赛 Pass" : "Event / series passes"}</span><strong>{scopedGrants.length}</strong></div>
          <p className="account-v2-note">{zh ? "小组赛 AI、AI 表现和复盘保持免费；付费阶段按赛事或系列赛解锁。" : "Group-stage AI, AI Performance and Review stay free; paid stages unlock by event or series."}</p>
          <a className="product-btn product-btn-primary" href="/billing">{zh ? "查看赛事 Pass" : "View competition passes"}<span>→</span></a>
        </section>

        <section className="account-v2-card">
          <div className="account-v2-card-heading">
            <div><span aria-hidden="true">◌</span><div><h2>{zh ? "通知" : "Notifications"}</h2><p>{zh ? "邮箱、QQ、微信和后续实时渠道都从这里进入。" : "Email, QQ, WeChat and future realtime channels live here."}</p></div></div>
          </div>
          <div className="account-v2-membership-row"><span>{zh ? "通知权限" : "Alert access"}</span><strong>{activeNotificationAccess ? (zh ? "已开放" : "Available") : (zh ? "未开放" : "Not available")}</strong></div>
          <a className="product-btn product-btn-secondary" href="/notifications">{zh ? "通知设置" : "Notification settings"}</a>
        </section>

        <section className="account-v2-card">
          <div className="account-v2-card-heading">
            <div><span aria-hidden="true">文</span><div><h2>{zh ? "语言" : "Language"}</h2><p>{zh ? "切换会立即应用到整个网站。" : "Changes apply across the site immediately."}</p></div></div>
          </div>
          <div className="account-v2-language" role="group" aria-label="Language">
            <button type="button" className={locale === "zh-CN" ? "is-active" : ""} onClick={() => setLocale("zh-CN")}>中文</button>
            <button type="button" className={locale === "en" ? "is-active" : ""} onClick={() => setLocale("en")}>English</button>
          </div>
        </section>
      </div>

      <section className="account-v2-danger">
        <div><strong>{zh ? "退出当前账户" : "Sign out of this account"}</strong><p>{zh ? "只会结束当前浏览器会话，不会删除账户或会员记录。" : "This ends the current browser session. It does not delete your account or membership."}</p></div>
        <button type="button" disabled={logoutBusy} onClick={() => void signOut()}>{logoutBusy ? "…" : (zh ? "退出登录" : "Sign out")}</button>
        {logoutError && <span role="alert">{logoutError}</span>}
      </section>
    </div>
  );
}

function formatDate(value: string, locale: "zh-CN" | "en") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric"
  }).format(date);
}
