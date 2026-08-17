import React from "react";
import {
  requestLoginCode,
  socialLoginHref,
  verifyLoginCode,
  type AuthSessionState
} from "../authApi";
import { useI18n } from "../i18n";

interface LoginDialogProps {
  session: AuthSessionState | undefined;
  onClose: () => void;
  onAuthenticated: (session: AuthSessionState) => void;
}

export const LoginDialog: React.FC<LoginDialogProps> = ({ session, onClose, onAuthenticated }) => {
  const { locale } = useI18n();
  const [email, setEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [phase, setPhase] = React.useState<"email" | "code">("email");
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const providers = session?.providers ?? { email: Boolean(session?.enabled), google: false, steam: false };
  const returnTo = `${window.location.pathname}${window.location.search}`;

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const error = params.get("auth_error");
    if (error) {
      setMessage(locale === "zh-CN" ? "第三方登录没有完成，请再试一次。" : "Social sign-in did not complete. Please try again.");
    }
  }, [locale]);

  const sendCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await requestLoginCode(email.trim());
      setPhase("code");
      setMessage(
        result.sent
          ? locale === "zh-CN"
            ? "验证码已发送。"
            : "Verification code sent."
          : locale === "zh-CN"
            ? `刚刚已经发送过验证码，${result.retry_after_seconds} 秒后可重新发送。`
            : `A code was already sent. Try again in ${result.retry_after_seconds}s.`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const confirmCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      onAuthenticated(await verifyLoginCode(email.trim(), code.trim()));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const startSocial = (provider: "google" | "steam") => {
    window.location.assign(socialLoginHref(provider, returnTo));
  };

  return (
    <div className="login-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="login-dialog" role="dialog" aria-modal="true" aria-labelledby="login-dialog-title">
        <button className="login-dialog-close" type="button" onClick={onClose} aria-label={locale === "zh-CN" ? "关闭" : "Close"}>×</button>
        <div className="login-dialog-brand"><span className="product-brand-mark" aria-hidden="true"><i /><b /></span></div>
        <h2 id="login-dialog-title">{locale === "zh-CN" ? "登录 Dota AI Decision Lab" : "Sign in to Dota AI Decision Lab"}</h2>
        <p>{locale === "zh-CN" ? "继续关注赛事，查看你的会员权限和 AI 功能。" : "Follow matches and access your membership and AI features."}</p>

        <div className="social-login-stack">
          <button type="button" disabled={!providers.google} onClick={() => startSocial("google")}>
            <span className="social-provider-mark google-mark" aria-hidden="true">G</span>
            <strong>{locale === "zh-CN" ? "使用 Google 账号继续" : "Continue with Google"}</strong>
            {!providers.google && <small>{locale === "zh-CN" ? "未配置" : "Not configured"}</small>}
          </button>
          <button type="button" disabled={!providers.steam} onClick={() => startSocial("steam")}>
            <span className="social-provider-mark steam-mark" aria-hidden="true">S</span>
            <strong>{locale === "zh-CN" ? "使用 Steam 登录" : "Continue with Steam"}</strong>
            {!providers.steam && <small>{locale === "zh-CN" ? "未配置" : "Not configured"}</small>}
          </button>
        </div>

        <div className="login-divider"><span>{locale === "zh-CN" ? "或使用邮箱" : "or use email"}</span></div>

        {phase === "email" ? (
          <form onSubmit={(event) => void sendCode(event)} className="email-login-form">
            <label htmlFor="north-star-email">{locale === "zh-CN" ? "邮箱" : "Email"}</label>
            <input id="north-star-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" disabled={busy || !providers.email} />
            <button className="login-primary-action" type="submit" disabled={busy || !providers.email || !email.trim()}>{busy ? "…" : locale === "zh-CN" ? "发送验证码" : "Send code"}</button>
          </form>
        ) : (
          <form onSubmit={(event) => void confirmCode(event)} className="email-login-form">
            <div className="login-code-summary">
              <span>{locale === "zh-CN" ? "验证码已发送至" : "Code sent to"}</span><strong>{email}</strong>
            </div>
            <label htmlFor="north-star-code">{locale === "zh-CN" ? "6 位验证码" : "6-digit code"}</label>
            <input id="north-star-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" disabled={busy} />
            <button className="login-primary-action" type="submit" disabled={busy || code.length !== 6}>{busy ? "…" : locale === "zh-CN" ? "确认登录" : "Sign in"}</button>
            <button className="login-text-action" type="button" onClick={() => { setPhase("email"); setCode(""); setMessage(null); }}>{locale === "zh-CN" ? "换一个邮箱" : "Use another email"}</button>
          </form>
        )}
        {message && <div className="login-dialog-message" role="status">{message}</div>}
        <small className="login-dialog-footnote">{locale === "zh-CN" ? "无需密码。Steam 登录不会把你的 Steam 密码提供给本站。" : "No password required. Steam never shares your Steam password with this site."}</small>
      </section>
    </div>
  );
};
