import React, { useEffect, useMemo, useState } from "react";
import { requestLoginCode, verifyLoginCode, type AuthSessionState } from "../authApi";
import { useI18n } from "../i18n";

interface LoginPageProps {
  onAuthenticated: (session: AuthSessionState) => void;
}

const copy = {
  en: {
    eyebrow: "Dota AI Decision Lab",
    title: "Sign in with email",
    description: "No password. We’ll send a one-time 6-digit code to your email.",
    emailLabel: "Email address",
    emailPlaceholder: "you@example.com",
    sendCode: "Send login code",
    sending: "Sending…",
    codeTitle: "Check your email",
    codeDescription: "Enter the 6-digit code sent to",
    codeLabel: "Login code",
    codePlaceholder: "000000",
    verify: "Sign in",
    verifying: "Verifying…",
    changeEmail: "Use another email",
    resend: "Resend code",
    resendIn: "Resend in {seconds}s",
    privacy: "The code expires in 10 minutes and can only be used once.",
    invalidEmail: "Enter a valid email address.",
    deliveryFailed: "We couldn’t send the login email. Check the mail configuration and try again.",
    invalidCode: "That code is invalid or expired. Request a new code and try again.",
    genericError: "Sign-in failed. Please try again.",
    secureSession: "Secure session · HttpOnly cookie · no password stored"
  },
  "zh-CN": {
    eyebrow: "Dota AI Decision Lab",
    title: "使用邮箱登录",
    description: "无需密码。我们会向你的邮箱发送一个 6 位一次性验证码。",
    emailLabel: "邮箱地址",
    emailPlaceholder: "you@example.com",
    sendCode: "发送登录验证码",
    sending: "正在发送…",
    codeTitle: "检查你的邮箱",
    codeDescription: "请输入发送到以下邮箱的 6 位验证码",
    codeLabel: "登录验证码",
    codePlaceholder: "000000",
    verify: "登录",
    verifying: "正在验证…",
    changeEmail: "更换邮箱",
    resend: "重新发送",
    resendIn: "{seconds} 秒后可重发",
    privacy: "验证码 10 分钟后失效，并且只能使用一次。",
    invalidEmail: "请输入有效的邮箱地址。",
    deliveryFailed: "登录邮件发送失败，请检查邮件配置后重试。",
    invalidCode: "验证码错误或已失效，请重新获取后再试。",
    genericError: "登录失败，请稍后重试。",
    secureSession: "安全会话 · HttpOnly Cookie · 不保存密码"
  }
} as const;

export const LoginPage: React.FC<LoginPageProps> = ({ onAuthenticated }) => {
  const { locale, setLocale } = useI18n();
  const t = copy[locale];
  const [stage, setStage] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown > 0]);

  const normalizedCode = useMemo(() => code.replace(/\D/g, "").slice(0, 6), [code]);

  const sendCode = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await requestLoginCode(email.trim());
      setStage("code");
      setCooldown(result.retry_after_seconds);
    } catch (cause) {
      setError(loginErrorMessage(cause, t));
    } finally {
      setBusy(false);
    }
  };

  const submitEmail = async (event: React.FormEvent) => {
    event.preventDefault();
    await sendCode();
  };

  const submitCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (normalizedCode.length !== 6) {
      setError(t.invalidCode);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await verifyLoginCode(email.trim(), normalizedCode);
      onAuthenticated(session);
    } catch (cause) {
      setError(loginErrorMessage(cause, t));
    } finally {
      setBusy(false);
    }
  };

  const changeEmail = () => {
    setStage("email");
    setCode("");
    setError(null);
  };

  return (
    <main className="auth-page">
      <div className="auth-ambient auth-ambient-one" />
      <div className="auth-ambient auth-ambient-two" />
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-card-header">
          <div className="auth-brand-mark">❖</div>
          <div>
            <div className="auth-eyebrow">{t.eyebrow}</div>
            <h1 id="auth-title">{stage === "email" ? t.title : t.codeTitle}</h1>
          </div>
        </div>

        {stage === "email" ? (
          <form className="auth-form" onSubmit={submitEmail}>
            <p className="auth-description">{t.description}</p>
            <label className="auth-field">
              <span>{t.emailLabel}</span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                maxLength={320}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={t.emailPlaceholder}
                autoFocus
              />
            </label>
            {error && <div className="auth-error" role="alert">{error}</div>}
            <button className="auth-primary-btn" type="submit" disabled={busy || !email.trim()}>
              {busy ? t.sending : t.sendCode}
            </button>
          </form>
        ) : (
          <form className="auth-form" onSubmit={submitCode}>
            <p className="auth-description">
              {t.codeDescription}<strong className="auth-email-target">{email.trim()}</strong>
            </p>
            <label className="auth-field auth-code-field">
              <span>{t.codeLabel}</span>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={6}
                value={normalizedCode}
                onChange={(event) => setCode(event.target.value)}
                placeholder={t.codePlaceholder}
                autoFocus
              />
            </label>
            {error && <div className="auth-error" role="alert">{error}</div>}
            <button className="auth-primary-btn" type="submit" disabled={busy || normalizedCode.length !== 6}>
              {busy ? t.verifying : t.verify}
            </button>
            <div className="auth-secondary-actions">
              <button type="button" onClick={changeEmail}>{t.changeEmail}</button>
              <button type="button" disabled={busy || cooldown > 0} onClick={() => void sendCode()}>
                {cooldown > 0 ? t.resendIn.replace("{seconds}", String(cooldown)) : t.resend}
              </button>
            </div>
            <p className="auth-privacy">{t.privacy}</p>
          </form>
        )}

        <footer className="auth-footer">
          <span>{t.secureSession}</span>
          <div className="auth-language-switcher" aria-label="Language">
            <button
              className={locale === "zh-CN" ? "active" : ""}
              onClick={() => setLocale("zh-CN")}
              type="button"
            >
              中文
            </button>
            <span>/</span>
            <button
              className={locale === "en" ? "active" : ""}
              onClick={() => setLocale("en")}
              type="button"
            >
              EN
            </button>
          </div>
        </footer>
      </section>
    </main>
  );
};

function loginErrorMessage(
  cause: unknown,
  t: (typeof copy)[keyof typeof copy]
): string {
  const message = cause instanceof Error ? cause.message.toLowerCase() : "";
  if (message.includes("invalid email")) return t.invalidEmail;
  if (message.includes("delivery failed")) return t.deliveryFailed;
  if (message.includes("invalid or expired")) return t.invalidCode;
  return t.genericError;
}
