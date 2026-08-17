import React, { lazy, Suspense } from "react";
import type { AuthSessionState } from "../authApi";
import { useI18n } from "../i18n";

const ReviewPage = lazy(() =>
  import("./ReviewPage").then((module) => ({ default: module.ReviewPage }))
);
const AiPerformancePage = lazy(() =>
  import("./AiPerformancePage").then((module) => ({ default: module.AiPerformancePage }))
);
const NotificationCenterPage = lazy(() =>
  import("./NotificationCenterPage").then((module) => ({
    default: module.NotificationCenterPage
  }))
);
const BillingPage = lazy(() =>
  import("./BillingPage").then((module) => ({ default: module.BillingPage }))
);

const AI_DECISIONS_ENTITLEMENT = "ai_decisions";
const REALTIME_NOTIFICATIONS_ENTITLEMENT = "realtime_notifications";

export type PremiumSurfaceKey = "performance" | "review" | "billing" | "notifications";

export function PremiumSurface({
  surface,
  session,
  authLoading,
  onLogin
}: {
  surface: PremiumSurfaceKey;
  session: AuthSessionState | undefined;
  authLoading: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);
  const hasGlobalAi = Boolean(session?.entitlements?.includes(AI_DECISIONS_ENTITLEMENT));
  const hasGlobalNotifications = Boolean(
    session?.entitlements?.includes(REALTIME_NOTIFICATIONS_ENTITLEMENT)
  );
  const hasNotificationAccess = Boolean(
    hasGlobalNotifications ||
      session?.grants?.some((grant) => grant.entitlement === REALTIME_NOTIFICATIONS_ENTITLEMENT)
  );
  const hasPro = hasGlobalAi && hasGlobalNotifications;

  if (surface === "billing") {
    return (
      <PremiumShellFrame surface={surface}>
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载订阅方案…" : "Loading plans…"} />}>
          <BillingPage authenticated={signedIn} hasPro={hasPro} onLogin={onLogin} />
        </Suspense>
      </PremiumShellFrame>
    );
  }

  if (authLoading) {
    return <PremiumLoading label={locale === "zh-CN" ? "正在确认账号权限…" : "Checking account access…"} />;
  }

  if (surface === "notifications") {
    if (!hasNotificationAccess || !session?.user) {
      return (
        <ProductAccessGate
          kind="notifications"
          authenticated={signedIn}
          authEnabled={session?.enabled !== false}
          onLogin={onLogin}
        />
      );
    }
    return (
      <PremiumShellFrame surface={surface}>
        <Suspense fallback={<PremiumLoading label="Notification Center…" />}>
          <NotificationCenterPage userEmail={session.user.email} />
        </Suspense>
      </PremiumShellFrame>
    );
  }

  if (!hasGlobalAi) {
    return (
      <ProductAccessGate
        kind={surface}
        authenticated={signedIn}
        authEnabled={session?.enabled !== false}
        onLogin={onLogin}
      />
    );
  }

  if (surface === "performance") {
    return (
      <PremiumShellFrame surface={surface}>
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载 AI 表现…" : "Loading AI performance…"} />}>
          <AiPerformancePage embedded />
        </Suspense>
      </PremiumShellFrame>
    );
  }

  return (
    <PremiumShellFrame surface={surface}>
      <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载复盘…" : "Loading review…"} />}>
        <ReviewPage embedded />
      </Suspense>
    </PremiumShellFrame>
  );
}

function PremiumShellFrame({ surface, children }: { surface: PremiumSurfaceKey; children: React.ReactNode }) {
  return <div className={`product-premium-surface premium-${surface}`}>{children}</div>;
}

function PremiumLoading({ label }: { label: string }) {
  return (
    <main className="product-premium-loading" aria-live="polite">
      <span aria-hidden="true" />
      <strong>{label}</strong>
    </main>
  );
}

function ProductAccessGate({
  kind,
  authenticated,
  authEnabled,
  onLogin
}: {
  kind: "performance" | "review" | "notifications";
  authenticated: boolean;
  authEnabled: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const copy = accessCopy(kind, locale);
  return (
    <main className="product-access-gate product-container">
      <section className="product-access-card">
        <div className="product-access-mark" aria-hidden="true">✦</div>
        <span className="home-eyebrow">{kind === "notifications" ? "REALTIME ACCESS" : "PRO INTELLIGENCE"}</span>
        <h1>{copy.title}</h1>
        <p>{copy.description}</p>
        <div className="product-access-boundary">
          <div><i aria-hidden="true">✓</i><span><strong>{copy.publicTitle}</strong><small>{copy.publicText}</small></span></div>
          <div className="is-premium"><i aria-hidden="true">✦</i><span><strong>{copy.premiumTitle}</strong><small>{copy.premiumText}</small></span></div>
        </div>
        {!authEnabled ? (
          <div className="product-access-status is-error" role="status">{copy.disabled}</div>
        ) : !authenticated ? (
          <div className="product-access-actions">
            <button className="product-btn product-btn-primary" type="button" onClick={onLogin}>{copy.login}<span>→</span></button>
            <a className="product-btn product-btn-secondary" href="/billing">{copy.plans}</a>
          </div>
        ) : (
          <>
            <div className="product-access-status" role="status">{copy.denied}</div>
            <a className="product-btn product-btn-primary" href="/billing">{copy.plans}<span>→</span></a>
          </>
        )}
      </section>
    </main>
  );
}

function accessCopy(kind: "performance" | "review" | "notifications", locale: string) {
  const zh = locale === "zh-CN";
  if (kind === "notifications") {
    return {
      title: zh ? "实时通知根据你的比赛权限开放" : "Realtime alerts follow your match access",
      description: zh
        ? "全局 Pro 或有效的系列赛通行证都可以使用通知中心。真正发送前，系统还会再次检查这场比赛是否在你的权限范围内。"
        : "Global Pro or an active series pass can use the Notification Center. Access is checked again against the match before every paid alert is sent.",
      publicTitle: zh ? "比赛信息继续公开" : "Match information stays public",
      publicText: zh ? "赛程、比分、Draft、Live 与赛果不需要通知权限。" : "Schedule, score, Draft, live state and results do not require alert access.",
      premiumTitle: zh ? "通知属于付费能力" : "Alerts are paid capability",
      premiumText: zh ? "邮箱、QQ、微信和未来实时渠道只发送你有权限的比赛。" : "Email, QQ, WeChat and future realtime channels only send matches covered by your access.",
      disabled: zh ? "当前运行环境尚未启用登录，因此用户级实时通知保持关闭。" : "Authentication is disabled, so user-scoped realtime alerts remain closed.",
      denied: zh ? "当前账号没有有效的实时通知权限。" : "This account does not have an active realtime notification grant.",
      login: zh ? "登录并检查权限" : "Sign in to check access",
      plans: zh ? "查看 AI 权益" : "Explore AI access"
    };
  }

  const performance = kind === "performance";
  return {
    title: zh
      ? performance ? "AI 表现榜属于全局 Pro" : "跨比赛 AI 复盘属于全局 Pro"
      : performance ? "AI Performance requires global Pro" : "Cross-match AI Review requires global Pro",
    description: zh
      ? performance
        ? "这里比较不同 AI 配置跨赛事的 Shadow 表现、预测质量和逐笔审计，因此只开放给全局 Pro；单个系列赛通行证不会解锁全局历史。"
        : "这里把多场比赛的 AI 判断放在同一套赛后口径里比较，因此只开放给全局 Pro；系列赛通行证仍然只覆盖所购买赛事。"
      : performance
        ? "This surface compares cross-event Shadow performance, prediction quality and position audit history, so it requires global Pro. A series pass does not unlock global model history."
        : "This surface compares AI calls across matches under one post-match methodology, so it requires global Pro. A series pass remains limited to the purchased series.",
    publicTitle: zh ? "赛事与比赛保持公开" : "Events and matches stay public",
    publicText: zh ? "赛程、比分、Draft、Live、市场上下文和赛果不在付费墙后。" : "Schedule, scores, Draft, live state, market context and results remain outside the paywall.",
    premiumTitle: zh ? performance ? "跨赛事模型历史" : "跨比赛 AI 历史" : performance ? "Cross-event model history" : "Cross-match AI history",
    premiumText: zh ? "付费层解锁的是 AI 分析深度，不是基础比赛可见性。" : "Paid access unlocks AI depth, not basic match visibility.",
    disabled: zh ? "当前运行环境尚未启用登录，因此全局 AI 接口保持关闭。" : "Authentication is disabled, so global AI access remains closed.",
    denied: zh ? "当前账号尚未拥有全局 Pro 权限。" : "This account does not have global Pro access yet.",
    login: zh ? "登录并检查权限" : "Sign in to check access",
    plans: zh ? "查看 Pro 与 Series Pass" : "View Pro and Series Pass"
  };
}
