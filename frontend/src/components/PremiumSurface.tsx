import React, { lazy, Suspense } from "react";
import type { AuthSessionState } from "../authApi";
import { useI18n } from "../i18n";
import { UiIcon } from "./VisualIdentity";

const ReviewPage = lazy(() =>
  import("./ReviewPage").then((module) => ({ default: module.ReviewPage }))
);
const AiPerformanceExperience = lazy(() =>
  import("./AiPerformanceExperience").then((module) => ({
    default: module.AiPerformanceExperience
  }))
);
const NotificationCenterPage = lazy(() =>
  import("./NotificationCenterPage").then((module) => ({
    default: module.NotificationCenterPage
  }))
);
const BillingPage = lazy(() =>
  import("./BillingPage").then((module) => ({ default: module.BillingPage }))
);

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
  const hasGlobalNotifications = Boolean(
    session?.entitlements?.includes(REALTIME_NOTIFICATIONS_ENTITLEMENT)
  );
  const hasNotificationAccess = Boolean(
    hasGlobalNotifications ||
      session?.grants?.some((grant) => grant.entitlement === REALTIME_NOTIFICATIONS_ENTITLEMENT)
  );
  if (surface === "billing") {
    return (
      <PremiumShellFrame surface={surface}>
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载会员方案…" : "Loading access plans…"} />}>
          <BillingPage authenticated={signedIn} onLogin={onLogin} />
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
        <PremiumProductIntro surface={surface} />
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载通知设置…" : "Loading notifications…"} />}>
          <NotificationCenterPage userEmail={session.user.email} />
        </Suspense>
      </PremiumShellFrame>
    );
  }

  if (surface === "performance") {
    return (
      <PremiumShellFrame surface={surface}>
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载 AI 表现…" : "Loading AI performance…"} />}>
          <AiPerformanceExperience />
        </Suspense>
      </PremiumShellFrame>
    );
  }

  return (
    <PremiumShellFrame surface={surface}>
      <PremiumProductIntro surface={surface} />
      <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载复盘…" : "Loading review…"} />}>
        <ReviewPage />
      </Suspense>
    </PremiumShellFrame>
  );
}

function PremiumShellFrame({ surface, children }: { surface: PremiumSurfaceKey; children: React.ReactNode }) {
  return <div className={`product-premium-surface premium-${surface}`}>{children}</div>;
}

function PremiumProductIntro({ surface }: { surface: PremiumSurfaceKey }) {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const copy = premiumIntroCopy(surface, zh);
  return (
    <section className={`premium-product-intro premium-product-intro-${surface} product-container`}>
      <span className="home-eyebrow">{copy.eyebrow}</span>
      <h1>{copy.title}</h1>
      <p>{copy.description}</p>
      {copy.notes.length > 0 && (
        <div className="premium-product-notes" aria-label={zh ? "说明" : "Notes"}>
          {copy.notes.map((note) => <span key={note}>{note}</span>)}
        </div>
      )}
    </section>
  );
}

function premiumIntroCopy(surface: PremiumSurfaceKey, zh: boolean) {
  if (surface === "performance") {
    return {
      eyebrow: zh ? "AI 表现" : "AI PERFORMANCE",
      title: zh ? "AI 表现榜" : "AI Performance",
      description: zh
        ? "所有用户都可以查看模型在统一模拟规则和起始资金下的长期表现。这里的数据不是实际下注记录，也不代表真实资金收益。"
        : "Everyone can compare long-term model performance under the same simulated rules and starting bankroll. These are not real bets or real-money returns.",
      notes: zh ? ["统一结算规则", "Shadow 模拟资金", "不代表真实下注"] : ["Same settlement rules", "Shadow bankroll", "Not real betting"]
    };
  }
  if (surface === "review") {
    return {
      eyebrow: zh ? "比赛复盘" : "MATCH REVIEW",
      title: zh ? "回看结果，也回看 AI 当时怎么判断" : "Review the result and the AI call that led to it",
      description: zh
        ? "所有用户都可以把比赛结果、关键赔率变化和 AI 判断放回同一条时间线上，查看模型为什么这样判断，以及最后是否经得住赛后验证。"
        : "Everyone can put the result, important market changes and AI calls back on one timeline and inspect how the model held up after the match.",
      notes: zh ? ["按比赛回看", "保留当时快照", "赛后统一验证"] : ["Match-by-match", "Original snapshots", "Consistent post-match review"]
    };
  }
  if (surface === "billing") {
    return {
      eyebrow: zh ? "会员" : "MEMBERSHIP",
      title: zh ? "选择适合你的方案" : "Choose the access that fits you",
      description: zh
        ? "小组赛与确认赛果后的基础 AI 决策公开。系列赛或赛事 Pass 解锁进行中的完整 AI 与实时通知。"
        : "Group-stage and confirmed post-match core AI decisions are public. A Series or Event Pass unlocks full live AI and realtime alerts.",
      notes: zh ? ["小组赛免费", "系列赛 Pass", "赛事 Pass"] : ["Group stage free", "Series Pass", "Event Pass"]
    };
  }
  return {
    eyebrow: zh ? "通知" : "NOTIFICATIONS",
    title: zh ? "只接收你真正关心的比赛提醒" : "Get alerts only for the matches you care about",
    description: zh
      ? "选择邮箱、QQ、微信等接收渠道。通知发送前会再次检查赛事权限，退款或失去 Pass 后不会继续收到付费提醒。"
      : "Choose email, QQ, WeChat or other delivery channels. Match access is checked again before every alert, so refunded passes stop receiving paid notifications.",
    notes: zh ? ["按权限发送", "多渠道", "随时关闭"] : ["Access-aware", "Multiple channels", "Turn off anytime"]
  };
}

function PremiumLoading({ label }: { label: string }) {
  return (
    <div className="product-premium-loading" aria-live="polite">
      <span aria-hidden="true" />
      <strong>{label}</strong>
    </div>
  );
}

function ProductAccessGate({
  kind,
  authenticated,
  authEnabled,
  onLogin
}: {
  kind: "notifications";
  authenticated: boolean;
  authEnabled: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const copy = accessCopy(kind, locale);
  return (
    <div className="product-access-gate product-container">
      <section className="product-access-card">
        <div className="product-access-mark" aria-hidden="true"><UiIcon name="spark" size={22} /></div>
        <span className="home-eyebrow">REALTIME ACCESS</span>
        <h1>{copy.title}</h1>
        <p>{copy.description}</p>
        <div className="product-access-boundary">
          <div><i aria-hidden="true"><UiIcon name="check" size={14} /></i><span><strong>{copy.publicTitle}</strong><small>{copy.publicText}</small></span></div>
          <div className="is-premium"><i aria-hidden="true"><UiIcon name="spark" size={14} /></i><span><strong>{copy.premiumTitle}</strong><small>{copy.premiumText}</small></span></div>
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
    </div>
  );
}

function accessCopy(_kind: "notifications", locale: string) {
  const zh = locale === "zh-CN";
  return {
    title: zh ? "通知功能需要有效的赛事 Pass" : "Notifications require an active Competition Pass",
    description: zh
      ? "购买赛事 Pass 或系列赛 Pass 后，可以绑定邮箱、QQ 和微信；系统只会发送你仍然有权限查看的比赛。"
      : "After buying an Event Pass or Series Pass, you can bind email, QQ or WeChat. Alerts are sent only for matches your account can still access.",
    publicTitle: zh ? "比赛信息继续公开" : "Match information stays public",
    publicText: zh ? "赛程、比分、Draft、Live 与赛果不需要通知权限。" : "Schedule, score, Draft, live state and results do not require alert access.",
    premiumTitle: zh ? "Pass 用户可接收提醒" : "Pass holders can receive alerts",
    premiumText: zh ? "邮箱、QQ、微信和未来实时渠道只发送你有权限的比赛。" : "Email, QQ, WeChat and future realtime channels only send matches covered by your access.",
    disabled: zh ? "当前运行环境没有启用登录，因此通知功能暂时关闭。" : "Authentication is disabled in this environment, so notifications are unavailable.",
    denied: zh ? "当前账号没有有效的赛事或系列赛 Pass。" : "This account does not have an active Event or Series Pass.",
    login: zh ? "登录" : "Sign in",
    plans: zh ? "查看赛事 Pass" : "View competition passes"
  };
}
