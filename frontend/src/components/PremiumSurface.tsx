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
        <PremiumProductIntro surface={surface} />
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
        <PremiumProductIntro surface={surface} />
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载通知设置…" : "Loading notifications…"} />}>
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
        <PremiumProductIntro surface={surface} />
        <Suspense fallback={<PremiumLoading label={locale === "zh-CN" ? "正在加载 AI 表现…" : "Loading AI performance…"} />}>
          <AiPerformancePage />
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
        ? "所有模型按照同一套模拟规则和起始资金进行结算，用来比较长期表现。这里的数据不是实际下注记录，也不代表真实资金收益。"
        : "Every model is settled under the same simulated rules and starting bankroll so long-term performance can be compared fairly. These are not real bets or real-money returns.",
      notes: zh ? ["统一结算规则", "Shadow 模拟资金", "不代表真实下注"] : ["Same settlement rules", "Shadow bankroll", "Not real betting"]
    };
  }
  if (surface === "review") {
    return {
      eyebrow: zh ? "比赛复盘" : "MATCH REVIEW",
      title: zh ? "回看结果，也回看 AI 当时怎么判断" : "Review the result and the AI call that led to it",
      description: zh
        ? "把比赛结果、关键赔率变化和 AI 判断放回同一条时间线上。先看发生了什么，再看模型为什么这样判断，以及最后是否经得住赛后验证。"
        : "Put the result, important market changes and AI calls back on one timeline. See what happened first, then inspect why the model made the call and how it held up after the match.",
      notes: zh ? ["按比赛回看", "保留当时快照", "赛后统一验证"] : ["Match-by-match", "Original snapshots", "Consistent post-match review"]
    };
  }
  if (surface === "billing") {
    return {
      eyebrow: zh ? "会员" : "MEMBERSHIP",
      title: zh ? "选择适合你的方案" : "Choose the access that fits you",
      description: zh
        ? "赛事、赛程、比分和基础比赛信息永久免费。Pro 解锁全站 AI 决策、AI 表现、完整复盘和通知；如果只关注一个赛事，也可以选择赛事 Pass。"
        : "Events, schedules, scores and core match data stay free. Pro unlocks site-wide AI decisions, AI Performance, full review and notifications; an event pass is available if you only follow one event.",
      notes: zh ? ["基础比赛免费", "Pro 全站 AI", "赛事 Pass 按需购买"] : ["Core matches free", "Site-wide AI with Pro", "Event passes when needed"]
    };
  }
  return {
    eyebrow: zh ? "通知" : "NOTIFICATIONS",
    title: zh ? "只接收你真正关心的比赛提醒" : "Get alerts only for the matches you care about",
    description: zh
      ? "选择邮箱、QQ、微信等接收渠道。通知发送前会再次检查比赛权限，过期的会员或 Pass 不会继续收到付费提醒。"
      : "Choose email, QQ, WeChat or other delivery channels. Match access is checked again before every alert, so expired membership or passes stop receiving paid notifications.",
    notes: zh ? ["按权限发送", "多渠道", "随时关闭"] : ["Access-aware", "Multiple channels", "Turn off anytime"]
  };
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
        <span className="home-eyebrow">{kind === "notifications" ? "REALTIME ACCESS" : "PRO"}</span>
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
      title: zh ? "通知功能需要有效的付费权限" : "Notifications require active paid access",
      description: zh
        ? "Pro 或有效的赛事 Pass 都可以使用通知。系统只会发送你仍然有权限查看的比赛。"
        : "Pro or an active event pass can use notifications. Alerts are sent only for matches your account can still access.",
      publicTitle: zh ? "比赛信息继续公开" : "Match information stays public",
      publicText: zh ? "赛程、比分、Draft、Live 与赛果不需要通知权限。" : "Schedule, score, Draft, live state and results do not require alert access.",
      premiumTitle: zh ? "付费用户可接收提醒" : "Paid users can receive alerts",
      premiumText: zh ? "邮箱、QQ、微信和未来实时渠道只发送你有权限的比赛。" : "Email, QQ, WeChat and future realtime channels only send matches covered by your access.",
      disabled: zh ? "当前运行环境没有启用登录，因此通知功能暂时关闭。" : "Authentication is disabled in this environment, so notifications are unavailable.",
      denied: zh ? "当前账号没有有效的通知权限。" : "This account does not have active notification access.",
      login: zh ? "登录" : "Sign in",
      plans: zh ? "查看会员方案" : "View membership"
    };
  }

  const performance = kind === "performance";
  return {
    title: zh
      ? performance ? "AI 表现榜属于 Pro 功能" : "跨比赛复盘属于 Pro 功能"
      : performance ? "AI Performance is a Pro feature" : "Cross-match review is a Pro feature",
    description: zh
      ? performance
        ? "这里会比较不同模型跨赛事的长期模拟表现和预测质量，因此需要全局 Pro。赛事 Pass 仍然只覆盖购买的赛事。"
        : "这里会把多场比赛的 AI 判断放在一起复盘，因此需要全局 Pro。赛事 Pass 仍然只覆盖购买的赛事。"
      : performance
        ? "This page compares long-term simulated performance and prediction quality across events, so it requires global Pro. Event passes remain limited to the purchased event."
        : "This page reviews AI calls across multiple matches, so it requires global Pro. Event passes remain limited to the purchased event.",
    publicTitle: zh ? "赛事与比赛保持公开" : "Events and matches stay public",
    publicText: zh ? "赛程、比分、Draft、Live、市场信息和赛果仍然免费。" : "Schedules, scores, Draft, live state, market context and results remain free.",
    premiumTitle: zh ? performance ? "长期 AI 表现" : "跨比赛 AI 复盘" : performance ? "Long-term AI performance" : "Cross-match AI review",
    premiumText: zh ? "付费解锁的是 AI 分析深度，不是基础比赛信息。" : "Paid access unlocks deeper AI analysis, not basic match visibility.",
    disabled: zh ? "当前运行环境没有启用登录，因此 Pro 功能暂时关闭。" : "Authentication is disabled in this environment, so Pro features are unavailable.",
    denied: zh ? "当前账号还不是全局 Pro。" : "This account does not have global Pro yet.",
    login: zh ? "登录" : "Sign in",
    plans: zh ? "查看 Pro 与赛事 Pass" : "View Pro and event passes"
  };
}
