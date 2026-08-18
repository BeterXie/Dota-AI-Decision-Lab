import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  claimReferral,
  createEventPassCheckout,
  createSeriesPassCheckout,
  fetchBillingAccount,
  fetchBillingOffers,
  fetchReferral,
  type PassOffer
} from "../billingApi";
import { useI18n } from "../i18n";
import "./billing.css";

export function BillingPage({
  authenticated,
  onLogin
}: {
  authenticated: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const params = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  const selectedSeriesId = params.get("series");
  const selectedEventId = params.get("event");
  const referralCode = params.get("ref");
  const offers = useQuery({
    queryKey: ["billing", "offers"],
    queryFn: fetchBillingOffers,
    staleTime: 60_000
  });
  const account = useQuery({
    queryKey: ["billing", "account"],
    queryFn: fetchBillingAccount,
    enabled: authenticated,
    refetchInterval: 30_000
  });
  const referral = useQuery({
    queryKey: ["promotions", "referral"],
    queryFn: fetchReferral,
    enabled: authenticated && Boolean(offers.data?.referral.enabled),
    staleTime: 30_000
  });
  const seriesCheckout = useMutation({
    mutationFn: createSeriesPassCheckout,
    onSuccess: ({ checkout_url }) => window.location.assign(checkout_url)
  });
  const eventCheckout = useMutation({
    mutationFn: createEventPassCheckout,
    onSuccess: ({ checkout_url }) => window.location.assign(checkout_url)
  });
  const referralClaim = useMutation({
    mutationFn: claimReferral,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["promotions", "referral"] });
    }
  });
  const hasSelectedSeriesGrant = Boolean(
    selectedSeriesId &&
      account.data?.grants.some(
        (grant) =>
          grant.scope_type === "SERIES" &&
          grant.scope_ref === selectedSeriesId &&
          grant.entitlement === "ai_decisions"
      )
  );
  const hasSelectedEventGrant = Boolean(
    selectedEventId &&
      account.data?.grants.some(
        (grant) =>
          grant.scope_type === "EVENT" &&
          grant.scope_ref === selectedEventId &&
          grant.entitlement === "ai_decisions"
      )
  );

  return (
    <div className="billing-page">
      <section className="billing-hero">
        <div>
          <a className="billing-back" href="/">← {locale === "zh-CN" ? "返回赛事" : "Back to events"}</a>
          <div className="billing-eyebrow">DOTA AI DECISION LAB · ACCESS</div>
          <h1>{locale === "zh-CN" ? "先体验，再解锁你关心的比赛" : "Start free, then unlock what you follow"}</h1>
          <p>
            {locale === "zh-CN"
              ? "小组赛 AI 决策、AI 表现和复盘对 Free 开放。付费阶段按系列赛或赛事购买，不按天数过期。"
              : "Group-stage AI decisions, AI Performance and Review are open on Free Access. Paid stages are unlocked by series or event, with no time expiry."}
          </p>
        </div>
        <div className="billing-status">
          <span>{locale === "zh-CN" ? "当前状态" : "Current access"}</span>
          <strong>FREE + PASSES</strong>
        </div>
      </section>

      {referralCode && <ReferralClaim code={referralCode} authenticated={authenticated} offers={offers.data?.referral.enabled ?? false} onLogin={onLogin} mutation={referralClaim} locale={locale} />}

      {offers.isLoading ? (
        <section className="billing-panel">{locale === "zh-CN" ? "正在读取方案…" : "Loading access options…"}</section>
      ) : offers.error || !offers.data ? (
        <section className="billing-panel billing-error" role="alert">{locale === "zh-CN" ? "支付方案暂时不可用。" : "Billing options are temporarily unavailable."}</section>
      ) : !offers.data.enabled ? (
        <section className="billing-panel">
          <strong>{locale === "zh-CN" ? "Paddle 尚未启用" : "Paddle is not enabled yet"}</strong>
          <p>{locale === "zh-CN" ? "Free 访问仍然可用；付费 Pass 需要先配置 Paddle Sandbox 商品和价格。" : "Free access remains available. Paid passes require Paddle Sandbox products and prices to be configured."}</p>
        </section>
      ) : (
        <>
          {selectedSeriesId && (
            <section className="billing-panel">
              <div className="billing-eyebrow">SERIES PASS · ONE BO SERIES</div>
              <h2>{locale === "zh-CN" ? "解锁当前系列赛" : "Unlock this BO series"}</h2>
              <p>{locale === "zh-CN" ? "永久解锁这场 BO 系列赛付费阶段的 AI 决策和实时通知；历史决策一直保留。" : "Permanently unlock paid-stage AI decisions and realtime notifications for this BO series. Historical decisions remain available."}</p>
              {hasSelectedSeriesGrant ? (
                <strong>{locale === "zh-CN" ? "✓ 当前账号已拥有这场系列赛权限" : "✓ This series is already unlocked"}</strong>
              ) : (
                <PassButton
                  offer={offers.data.series_pass}
                  authenticated={authenticated}
                  pending={seriesCheckout.isPending}
                  onLogin={onLogin}
                  onClick={() => seriesCheckout.mutate(selectedSeriesId)}
                  locale={locale}
                  label={locale === "zh-CN" ? "购买系列赛 Pass" : "Buy Series Pass"}
                />
              )}
            </section>
          )}

          {selectedEventId && (
            <section className="billing-panel">
              <div className="billing-eyebrow">EVENT PASS · ONE EVENT</div>
              <h2>{locale === "zh-CN" ? "解锁当前赛事" : "Unlock this event"}</h2>
              <p>{locale === "zh-CN" ? "永久覆盖该赛事全部系列赛的付费阶段 AI 决策和实时通知；历史决策一直保留。" : "Permanently cover paid-stage AI decisions and realtime notifications for every series in this event. Historical decisions remain available."}</p>
              {hasSelectedEventGrant ? (
                <strong>{locale === "zh-CN" ? "✓ 当前账号已拥有这项赛事权限" : "✓ This event is already unlocked"}</strong>
              ) : (
                <PassButton
                  offer={offers.data.event_pass}
                  authenticated={authenticated}
                  pending={eventCheckout.isPending}
                  onLogin={onLogin}
                  onClick={() => eventCheckout.mutate(selectedEventId)}
                  locale={locale}
                  label={locale === "zh-CN" ? "购买赛事 Pass" : "Buy Event Pass"}
                />
              )}
            </section>
          )}

          <section className="billing-grid" aria-label="Competition access options">
            <AccessCard title={locale === "zh-CN" ? "Free Access" : "Free Access"} eyebrow="FREE · DISCOVERY" copy={locale === "zh-CN" ? "小组赛 AI 决策、AI 表现和复盘全站开放。实时通知和付费阶段 AI 需要对应 Pass。" : "Group-stage AI decisions, AI Performance and Review are open. Realtime notifications and paid-stage AI need the relevant pass."} items={locale === "zh-CN" ? ["小组赛 AI 决策", "AI 表现", "比赛复盘"] : ["Group-stage AI decisions", "AI Performance", "Match Review"]} />
            <AccessCard title={locale === "zh-CN" ? "Series Pass" : "Series Pass"} eyebrow="SERIES · ONE-TIME" copy={locale === "zh-CN" ? "绑定一个 BO 系列赛，永久解锁该系列赛的付费阶段 AI 和实时通知。" : "Bind one BO series and permanently unlock its paid-stage AI and realtime notifications."} items={locale === "zh-CN" ? ["一个 BO 系列赛", "付费阶段 AI", "实时通知"] : ["One BO series", "Paid-stage AI", "Realtime notifications"]} />
            <AccessCard title={locale === "zh-CN" ? "Event Pass" : "Event Pass"} eyebrow="EVENT · ONE-TIME" copy={locale === "zh-CN" ? "绑定一个赛事，覆盖赛事内全部系列赛的付费阶段 AI 和实时通知。" : "Bind one event and cover paid-stage AI and realtime notifications for every series in it."} items={locale === "zh-CN" ? ["一个完整赛事", "所有付费阶段", "实时通知"] : ["One full event", "Every paid stage", "Realtime notifications"]} />
          </section>

          {(seriesCheckout.error || eventCheckout.error) && <section className="billing-panel billing-error" role="alert">{locale === "zh-CN" ? "支付请求失败，请稍后重试。" : "The payment request failed. Please try again."}</section>}
        </>
      )}

      {authenticated && referral.data?.enabled && (
        <section className="billing-panel">
          <div className="billing-eyebrow">INVITE & EARN</div>
          <h2>{locale === "zh-CN" ? "邀请好友" : "Invite friends"}</h2>
          <p>{locale === "zh-CN" ? `好友完成首次付费后，双方按活动规则获得奖励。当前已奖励 ${referral.data.rewarded_invites} 人。` : `Rewards are issued after a friend completes a first paid purchase. ${referral.data.rewarded_invites} referrals rewarded so far.`}</p>
          <span className="billing-method is-available">{referral.data.code ?? "—"}</span>
        </section>
      )}

      {account.data && account.data.passes.length > 0 && (
        <section className="billing-panel">
          <div className="billing-eyebrow">YOUR PASSES</div>
          <h2>{locale === "zh-CN" ? "已购买的范围" : "Purchased scopes"}</h2>
          <div className="billing-methods">
            {account.data.passes.filter((pass) => pass.status === "ACTIVE").map((pass) => (
              <span className="billing-method is-available" key={`${pass.scope_type}:${pass.canonical_event_id ?? pass.canonical_series_id}`}>
                {pass.scope_type === "EVENT" ? "Event Pass" : "Series Pass"}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function AccessCard({ title, eyebrow, copy, items }: { title: string; eyebrow: string; copy: string; items: string[] }) {
  return (
    <article className="billing-offer-card">
      <div className="billing-offer-kind">{eyebrow}</div>
      <h2>{title}</h2>
      <p className="billing-price-note">{copy}</p>
      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </article>
  );
}

function PassButton({ offer, authenticated, pending, onLogin, onClick, locale, label }: { offer: PassOffer; authenticated: boolean; pending: boolean; onLogin: () => void; onClick: () => void; locale: string; label: string }) {
  if (!offer.enabled) return <span className="billing-method">{locale === "zh-CN" ? "暂未开放" : "Unavailable"}</span>;
  return <button className="billing-checkout-btn" type="button" disabled={pending} onClick={authenticated ? onClick : onLogin}>{pending ? "…" : authenticated ? label : locale === "zh-CN" ? "登录后购买" : "Sign in to buy"}</button>;
}

function ReferralClaim({ code, authenticated, offers, onLogin, mutation, locale }: { code: string; authenticated: boolean; offers: boolean; onLogin: () => void; mutation: { isPending: boolean; isSuccess: boolean; error: Error | null; mutate: (code: string) => void }; locale: string }) {
  return (
    <section className="billing-panel">
      <div className="billing-eyebrow">REFERRAL</div>
      <h2>{locale === "zh-CN" ? "好友邀请" : "Friend referral"}</h2>
      <p>{locale === "zh-CN" ? `邀请码：${code}。完成首次付费后按活动规则发放奖励。` : `Referral code: ${code}. Rewards follow the campaign rules after the first paid purchase.`}</p>
      {!authenticated ? <button className="billing-checkout-btn" type="button" onClick={onLogin}>{locale === "zh-CN" ? "登录后领取" : "Sign in to claim"}</button> : offers ? <button className="billing-checkout-btn" type="button" disabled={mutation.isPending || mutation.isSuccess} onClick={() => mutation.mutate(code)}>{mutation.isSuccess ? locale === "zh-CN" ? "已领取" : "Claimed" : locale === "zh-CN" ? "领取邀请关系" : "Claim referral"}</button> : <span className="billing-method">{locale === "zh-CN" ? "活动未开放" : "Campaign inactive"}</span>}
      {mutation.error && <div className="billing-error" role="alert">{mutation.error.message}</div>}
    </section>
  );
}
