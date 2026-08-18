import React from "react";
import type { AuthSessionState } from "../authApi";
import { useI18n } from "../i18n";

export type ProductNavKey = "home" | "events" | "performance" | "review" | "billing";

interface ProductShellProps {
  active: ProductNavKey | null;
  session: AuthSessionState | undefined;
  onLogin: () => void;
  onLogout: () => Promise<void>;
  children: React.ReactNode;
}

const navItems: Array<{ key: ProductNavKey; href: string; zh: string; en: string }> = [
  { key: "home", href: "/", zh: "首页", en: "Home" },
  { key: "events", href: "/events", zh: "赛事", en: "Events" },
  { key: "performance", href: "/performance", zh: "AI 表现", en: "AI Performance" },
  { key: "review", href: "/review", zh: "复盘", en: "Review" },
  { key: "billing", href: "/billing", zh: "会员方案", en: "Access" }
];

export const ProductShell: React.FC<ProductShellProps> = ({
  active,
  session,
  onLogin,
  onLogout,
  children
}) => {
  const { locale, setLocale } = useI18n();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [navOpen, setNavOpen] = React.useState(false);
  const [logoutBusy, setLogoutBusy] = React.useState(false);
  const [logoutError, setLogoutError] = React.useState<string | null>(null);
  const menuRef = React.useRef<HTMLDivElement | null>(null);
  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);
  const user = session?.user ?? null;
  const label = user?.display_name || user?.email || (locale === "zh-CN" ? "Steam 用户" : "Steam user");

  React.useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const handleLogout = async () => {
    if (logoutBusy) return;
    setLogoutBusy(true);
    setLogoutError(null);
    try {
      await onLogout();
      window.location.assign("/");
    } catch {
      setLogoutError(locale === "zh-CN" ? "退出失败，请重试" : "Sign out failed. Try again.");
      setLogoutBusy(false);
    }
  };

  return (
    <div className="product-root">
      <header className="product-topbar">
        <a className="product-brand" href="/" aria-label="Dota AI Decision Lab">
          <span className="product-brand-mark" aria-hidden="true"><i /><b /></span>
          <span>Dota AI Decision Lab</span>
        </a>
        <button
          type="button"
          className={`product-nav-toggle ${navOpen ? "is-open" : ""}`}
          aria-label={navOpen ? (locale === "zh-CN" ? "关闭主导航" : "Close main navigation") : (locale === "zh-CN" ? "打开主导航" : "Open main navigation")}
          aria-expanded={navOpen}
          onClick={() => {
            setMenuOpen(false);
            setNavOpen((value) => !value);
          }}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <nav className={`product-main-nav ${navOpen ? "is-open" : ""}`} aria-label={locale === "zh-CN" ? "主导航" : "Main navigation"}>
          {navItems.map((item) => (
            <a
              key={item.key}
              href={item.href}
              className={active === item.key ? "is-active" : undefined}
              aria-current={active === item.key ? "page" : undefined}
              onClick={() => setNavOpen(false)}
            >
              {locale === "zh-CN" ? item.zh : item.en}
            </a>
          ))}
        </nav>
        <div className="product-account" ref={menuRef}>
          <button
            type="button"
            className={`product-avatar-button ${signedIn ? "is-signed-in" : ""}`}
            onClick={() => {
              setNavOpen(false);
              if (signedIn) setMenuOpen((value) => !value);
              else onLogin();
            }}
            aria-label={signedIn ? (locale === "zh-CN" ? "打开个人菜单" : "Open account menu") : (locale === "zh-CN" ? "登录" : "Sign in")}
            aria-expanded={signedIn ? menuOpen : undefined}
          >
            {signedIn && user?.avatar_url ? (
              <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" />
            ) : (
              <span aria-hidden="true">{signedIn ? label.slice(0, 1).toUpperCase() : "人"}</span>
            )}
          </button>
          {signedIn && menuOpen && (
            <div className="product-account-menu" role="menu">
              <div className="account-menu-head">
                <div className="account-menu-avatar">
                  {user?.avatar_url ? <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" /> : label.slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <strong>{label}</strong>
                  {user?.email && user.display_name ? <span>{user.email}</span> : null}
                </div>
              </div>
              <div className="account-menu-section">
                <a className="account-menu-row" href="/account" role="menuitem">
                  <span className="account-menu-icon" aria-hidden="true">◎</span>
                  <div><strong>{locale === "zh-CN" ? "个人信息" : "Account"}</strong><small>{locale === "zh-CN" ? "免费账户 · 赛事 Pass" : "Free access · Competition Passes"}</small></div>
                  <span className="menu-chevron">›</span>
                </a>
                <div className="account-menu-row language-row">
                  <span className="account-menu-icon" aria-hidden="true">文</span>
                  <strong>{locale === "zh-CN" ? "语言 / Language" : "Language / 语言"}</strong>
                  <div className="account-language-toggle" role="group" aria-label="Language">
                    <button type="button" className={locale === "zh-CN" ? "is-active" : ""} onClick={() => setLocale("zh-CN")}>中文</button>
                    <button type="button" className={locale === "en" ? "is-active" : ""} onClick={() => setLocale("en")}>EN</button>
                  </div>
                </div>
                <a className="account-menu-row" href="/notifications" role="menuitem">
                  <span className="account-menu-icon" aria-hidden="true">◌</span>
                  <strong>{locale === "zh-CN" ? "通知设置" : "Notifications"}</strong><span className="menu-chevron">›</span>
                </a>
                <a className="account-menu-row" href="/billing" role="menuitem">
                  <span className="account-menu-icon" aria-hidden="true">♔</span>
                  <strong>{locale === "zh-CN" ? "会员中心" : "Membership"}</strong><span className="menu-chevron">›</span>
                </a>
                <a className="account-menu-row admin-menu-entry" href="/admin/runtime" role="menuitem">
                  <span className="account-menu-icon" aria-hidden="true">⚙</span>
                  <div><strong>{locale === "zh-CN" ? "管理控制台" : "Admin control plane"}</strong><small>{locale === "zh-CN" ? "Runtime 配置与 AI 提供商" : "Runtime configuration & AI providers"}</small></div>
                  <span className="menu-chevron">›</span>
                </a>
              </div>
              <div className="account-menu-footer">
                <button type="button" disabled={logoutBusy} onClick={() => void handleLogout()}>
                  <span aria-hidden="true">↪</span>{logoutBusy ? "…" : locale === "zh-CN" ? "退出登录" : "Sign out"}
                </button>
                {logoutError && <span role="alert">{logoutError}</span>}
              </div>
            </div>
          )}
        </div>
      </header>
      <main className="product-page">{children}</main>
    </div>
  );
};
