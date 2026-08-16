import React, { useEffect, useMemo, useState } from "react";
import { requestLoginCode, verifyLoginCode, type AuthSessionState } from "../authApi";
import { useI18n } from "../i18n";

interface LoginPageProps {
  onAuthenticated: (session: AuthSessionState) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onAuthenticated }) => {
  const { locale, setLocale, t } = useI18n();
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

  const loginErrorMessage = (cause: unknown): string => {
    const message = cause instanceof Error ? cause.message.toLowerCase() : "";
    if (message.includes("invalid email")) return t("authInvalidEmail");
    if (message.includes("delivery failed")) return t("authDeliveryFailed");
    if (message.includes("invalid or expired")) return t("authInvalidCode");
    return t("authGenericError");
  };

  const sendCode = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await requestLoginCode(email.trim());
      setStage("code");
      setCooldown(result.retry_after_seconds);
    } catch (cause) {
      setError(loginErrorMessage(cause));
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
      setError(t("authInvalidCode"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await verifyLoginCode(email.trim(), normalizedCode);
      onAuthenticated(session);
    } catch (cause) {
      setError(loginErrorMessage(cause));
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
            <div className="auth-eyebrow">{t("authLoginEyebrow")}</div>
            <h1 id="auth-title">
              {stage === "email" ? t("authLoginTitle") : t("authCodeTitle")}
            </h1>
          </div>
        </div>

        {stage === "email" ? (
          <form className="auth-form" onSubmit={submitEmail}>
            <p className="auth-description">{t("authLoginDescription")}</p>
            <label className="auth-field">
              <span>{t("authEmailLabel")}</span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                maxLength={320}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={t("authEmailPlaceholder")}
                autoFocus
              />
            </label>
            {error && <div className="auth-error" role="alert">{error}</div>}
            <button className="auth-primary-btn" type="submit" disabled={busy || !email.trim()}>
              {busy ? t("authSending") : t("authSendCode")}
            </button>
          </form>
        ) : (
          <form className="auth-form" onSubmit={submitCode}>
            <p className="auth-description">
              {t("authCodeDescription")}
              <strong className="auth-email-target">{email.trim()}</strong>
            </p>
            <label className="auth-field auth-code-field">
              <span>{t("authCodeLabel")}</span>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={6}
                value={normalizedCode}
                onChange={(event) => setCode(event.target.value)}
                placeholder={t("authCodePlaceholder")}
                autoFocus
              />
            </label>
            {error && <div className="auth-error" role="alert">{error}</div>}
            <button
              className="auth-primary-btn"
              type="submit"
              disabled={busy || normalizedCode.length !== 6}
            >
              {busy ? t("authVerifying") : t("authVerify")}
            </button>
            <div className="auth-secondary-actions">
              <button type="button" onClick={changeEmail}>{t("authChangeEmail")}</button>
              <button type="button" disabled={busy || cooldown > 0} onClick={() => void sendCode()}>
                {cooldown > 0
                  ? t("authResendIn").replace("{seconds}", String(cooldown))
                  : t("authResend")}
              </button>
            </div>
            <p className="auth-privacy">{t("authCodePrivacy")}</p>
          </form>
        )}

        <footer className="auth-footer">
          <span>{t("authSecureSession")}</span>
          <div className="auth-language-switcher" aria-label={t("language")}>
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
