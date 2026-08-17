import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  claimReferral,
  createBillingCheckout,
  createBillingPortal,
  createSeriesPassCheckout,
  fetchBillingAccount,
  fetchBillingOffers,
  fetchReferral,
  type BillingOffer
} from "../billingApi";
import { useI18n } from "../i18n";
import "./billing.css";

export function BillingPage({
  authenticated,
  hasPro,
  onLogin
}: {
  authenticated: boolean;
  hasPro: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const params = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  const selectedSeriesId = params.get("series");
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
  const checkout = useMutation({
    mutationFn: createBillingCheckout,
    onSuccess: ({ checkout_url }) => window.location.assign(checkout_url)
  });
  const seriesCheckout = useMutation({
    mutationFn: createSeriesPassCheckout,
    onSuccess: ({ checkout_url }) => window.location.assign(checkout_url)
  });
  const portal = useMutation({
    mutationFn: createBillingPortal,
    onSuccess: ({ portal_url }) => window.location.assign(portal_url)
  });
  const referralClaim = useMutation({
    mutationFn: claimReferral,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["promotions", "referral"] });
    }
  });

  const activeBilling = account.data?.subscriptions.some(
    (item) => item.access_state === "ACTIVE" || item.provider_status === "active"
  );
  const hasSelectedSeriesGrant = Boolean(
    selectedSeriesId &&
      account.data?.grants.some(
        (grant) =>
          grant.scope_type === "SERIES" &&
          grant.scope_ref === selectedSeriesId &&
          grant.entitlement === "ai_decisions"
      )
  );
  const inviteLink =
    referral.data?.code && typeof window !== "undefined"
      ? `${window.location.origin}/billing?ref=${encodeURIComponent(referral.data.code)}`
      : null;

  return (
    <main className="billing-page">
      <section className="billing-hero">
        <div>
          <a className="billing-back" href="/">
            ← {locale === "zh-CN" ? "返回比赛" : "Back to matches"}
          </a>
          <div className="billing-eyebrow">DOTA AI DECISION LAB · ACCESS</div>
          <h1>{locale === "zh-CN" ? "选择你的 AI 权限" : "Choose your AI access"}</h1>
          <p>
            {locale === "zh-CN"
              ? "全局 Pro 解锁全部比赛；如果只关心当前 BO 系列赛，也可以购买更轻量的 Series Pass。邀请好友完成首次付费后还可以获得限时 Pro 奖励。"
              : "Global Pro unlocks every match. If you only care about one BO series, buy a lighter Series Pass. Referral rewards add time-limited Pro after the invited user completes a first paid purchase."}
          </p>
        </div>
        <div className={`billing-status ${hasPro ? "is-pro" : ""}`}>
          <span>{locale === "zh-CN" ? "全局状态" : "Global access"}</span>
          <strong>{hasPro ? "PRO" : "FREE"}</strong>
        </div>
      </section>

      {referralCode && (
        <section className="billing-panel">
          <div className="billing-eyebrow">REFERRAL</div>
          <h2>{locale === "zh-CN" ? "好友邀请" : "Friend referral"}</h2>
          <p>
            {locale === "zh-CN"
              ? `邀请代码：${referralCode}。领取邀请码不会立即送会员；你完成首次真实付费后，系统才会按照活动规则给双方发放奖励。`
              : `Referral code: ${referralCode}. Claiming the code does not grant membership immediately; rewards are issued only after your first verified paid purchase.`}
          </p>
          {!authenticated ? (
            <button className="billing-checkout-btn" type="button" onClick={onLogin}>
              {locale === "zh-CN" ? "登录后领取邀请" : "Sign in to claim referral"}
            </button>
          ) : offers.data?.referral.enabled ? (
            <button
              className="billing-checkout-btn"
              type="button"
              disabled={referralClaim.isPending || referralClaim.isSuccess}
              onClick={() => referralClaim.mutate(referralCode)}
            >
              {referralClaim.isSuccess
                ? locale === "zh-CN"
                  ? "已领取"
                  : "Claimed"
                : referralClaim.isPending
                  ? "…"
                  : locale === "zh-CN"
                    ? "领取邀请关系"
                    : "Claim referral"}
            </button>
          ) : (
            <p>{locale === "zh-CN" ? "当前邀请活动未开放。" : "Referral campaign is not active."}</p>
          )}
          {referralClaim.error && (
            <div className="billing-error" role="alert">
              {referralClaim.error.message}
            </div>
          )}
        </section>
      )}

      {offers.isLoading ? (
        <section className="billing-panel">{locale === "zh-CN" ? "正在读取方案…" : "Loading plans…"}</section>
      ) : offers.error || !offers.data ? (
        <section className="billing-panel billing-error" role="alert">
          {locale === "zh-CN" ? "支付方案暂时不可用。" : "Billing plans are temporarily unavailable."}
        </section>
      ) : !offers.data.enabled ? (
        <section className="billing-panel">
          <strong>{locale === "zh-CN" ? "Paddle 尚未启用" : "Paddle is not enabled yet"}</strong>
          <p>
            {locale === "zh-CN"
              ? "当前环境仍可测试 Free / Pro 权限，但真实结账需要先配置 Paddle Sandbox 或 Live 凭据与价格。"
              : "The current runtime can still test Free / Pro access, but real checkout needs Paddle Sandbox or Live credentials and catalog prices."}
          </p>
        </section>
      ) : (
        <>
          {selectedSeriesId && offers.data.series_pass.enabled && (
            <section className="billing-panel">
              <div className="billing-eyebrow">SERIES PASS · ONE MATCHUP</div>
              <h2>{locale === "zh-CN" ? "当前 BO 系列赛通行证" : "Current BO Series Pass"}</h2>
              <p>
                {locale === "zh-CN"
                  ? `只解锁系列赛 ${selectedSeriesId} 的 AI 决策和该系列赛实时通知；不会获得跨比赛 AI Review。权限默认持续 ${offers.data.series_pass.access_days ?? "配置"} 天，不自动续费。`
                  : `Unlock AI decisions and alerts only for series ${selectedSeriesId}; cross-match AI Review remains global-Pro only. Access lasts ${offers.data.series_pass.access_days ?? "the configured"} days and does not auto-renew.`}
              </p>
              <div className="billing-methods">
                <Method label="Card" value={offers.data.series_pass.payment_methods?.card ?? "one_time"} />
                <Method label="Alipay" value={offers.data.series_pass.payment_methods?.alipay ?? "one_time"} />
                <Method label="WeChat Pay" value={offers.data.series_pass.payment_methods?.wechat_pay ?? "one_time"} />
              </div>
              {hasSelectedSeriesGrant ? (
                <strong>{locale === "zh-CN" ? "✓ 当前账号已拥有这场系列赛权限" : "✓ This series is already unlocked"}</strong>
              ) : (
                <button
                  className="billing-checkout-btn"
                  type="button"
                  disabled={seriesCheckout.isPending}
                  onClick={() =>
                    authenticated ? seriesCheckout.mutate(selectedSeriesId) : onLogin()
                  }
                >
                  {seriesCheckout.isPending
                    ? "…"
                    : authenticated
                      ? locale === "zh-CN"
                        ? "购买本系列赛通行证"
                        : "Buy this Series Pass"
                      : locale === "zh-CN"
                        ? "登录后购买"
                        : "Sign in to buy"}
                </button>
              )}
            </section>
          )}

          <section className="billing-grid" aria-label="Pro billing offers">
            {offers.data.offers.map((offer) => (
              <OfferCard
                key={offer.key}
                offer={offer}
                locale={locale}
                authenticated={authenticated}
                busy={checkout.isPending}
                onLogin={onLogin}
                onCheckout={(key) => checkout.mutate(key)}
              />
            ))}
          </section>

          {(checkout.error || seriesCheckout.error || portal.error) && (
            <section className="billing-panel billing-error" role="alert">
              {locale === "zh-CN"
                ? "支付服务请求失败，请稍后重试。"
                : "The billing request failed. Please try again."}
            </section>
          )}

          <section className="billing-payment-boundary">
            <div>
              <div className="billing-eyebrow">CHINA PAYMENT METHODS</div>
              <h2>{locale === "zh-CN" ? "支付宝与微信支付" : "Alipay and WeChat Pay"}</h2>
              <p>
                {locale === "zh-CN"
                  ? "月订阅用于支持自动续费的支付方式；微信支付与 Series Pass 使用一次性购买，不伪装成自动续费。最终可用支付方式由 Paddle 在结账时根据地区、币种与账号审批决定。"
                  : "Monthly Pro is for payment methods that support recurring billing. WeChat Pay and Series Passes use one-time purchases rather than pretending to auto-renew. Paddle makes the final method decision at checkout."}
              </p>
            </div>
            <div>
              <div className="billing-eyebrow">CRYPTO / STABLECOIN</div>
              <h2>{locale === "zh-CN" ? "独立 Provider，默认关闭" : "Separate provider, disabled by default"}</h2>
              <p>
                {locale === "zh-CN"
                  ? "稳定币不会绕过现有账单系统。未来会作为独立 provider 接入同一 access-grant 生命周期，并单独处理主体、地区、资产网络和合规边界。"
                  : "Stablecoin payments will not bypass this billing system. A future adapter will feed the same access-grant lifecycle with explicit entity, jurisdiction, asset, and network rules."}
              </p>
            </div>
          </section>
        </>
      )}

      {authenticated && referral.data?.enabled && (
        <section className="billing-panel">
          <div className="billing-eyebrow">INVITE & EARN PRO</div>
          <h2>{locale === "zh-CN" ? "邀请好友送会员" : "Invite friends, earn Pro time"}</h2>
          <p>
            {locale === "zh-CN"
              ? `好友在注册后的 ${referral.data.reward.claim_window_days} 天内绑定你的邀请码，并完成首次真实付费后：你获得 ${referral.data.reward.inviter_days} 天 Pro，好友获得 ${referral.data.reward.invited_days} 天 Pro。每个邀请人最多奖励 ${referral.data.reward.max_rewards_per_inviter} 次。退款或拒付会撤销对应奖励。`
              : `If a friend claims your code within ${referral.data.reward.claim_window_days} days of signup and completes a first verified purchase, you get ${referral.data.reward.inviter_days} Pro days and they get ${referral.data.reward.invited_days} days. Up to ${referral.data.reward.max_rewards_per_inviter} rewarded referrals. Refunds or chargebacks revoke the linked reward.`}
          </p>
          <div className="billing-methods">
            <span className="billing-method is-available">
              {locale === "zh-CN" ? `邀请码 · ${referral.data.code ?? "—"}` : `Code · ${referral.data.code ?? "—"}`}
            </span>
            <span className="billing-method">
              {locale === "zh-CN"
                ? `已奖励 ${referral.data.rewarded_invites} 人`
                : `${referral.data.rewarded_invites} rewarded`}
            </span>
          </div>
          {inviteLink && (
            <button
              className="billing-checkout-btn"
              type="button"
              onClick={() => void navigator.clipboard?.writeText(inviteLink)}
            >
              {locale === "zh-CN" ? "复制邀请链接" : "Copy referral link"}
            </button>
          )}
        </section>
      )}

      {authenticated && (activeBilling || account.data?.subscriptions.length) ? (
        <section className="billing-manage">
          <div>
            <div className="billing-eyebrow">CUSTOMER PORTAL</div>
            <h2>{locale === "zh-CN" ? "管理订阅与账单" : "Manage subscription and billing"}</h2>
          </div>
          <button type="button" disabled={portal.isPending} onClick={() => portal.mutate()}>
            {portal.isPending
              ? "…"
              : locale === "zh-CN"
                ? "打开 Paddle 客户门户"
                : "Open Paddle customer portal"}
          </button>
        </section>
      ) : null}
    </main>
  );
}

function OfferCard({
  offer,
  locale,
  authenticated,
  busy,
  onLogin,
  onCheckout
}: {
  offer: BillingOffer;
  locale: string;
  authenticated: boolean;
  busy: boolean;
  onLogin: () => void;
  onCheckout: (key: string) => void;
}) {
  const fixedTerm = offer.kind === "fixed_term";
  const title = fixedTerm
    ? locale === "zh-CN"
      ? `Pro ${offer.grant_days} 天通行证`
      : `Pro ${offer.grant_days}-day Pass`
    : locale === "zh-CN"
      ? "Pro 月订阅"
      : "Pro Monthly";
  return (
    <article className="billing-offer-card">
      <div className="billing-offer-kind">{fixedTerm ? "GLOBAL · ONE-TIME" : "GLOBAL · RECURRING"}</div>
      <h2>{title}</h2>
      <p className="billing-price-note">
        {locale === "zh-CN"
          ? "整站 Pro：全部比赛 AI + 跨比赛复盘 + 全部实时通知。金额、税费与币种在 Paddle 结账页确认。"
          : "Global Pro: every match AI, cross-match review, and all realtime alerts. Amount, taxes, and currency are confirmed in Paddle checkout."}
      </p>
      <ul>
        <li>{locale === "zh-CN" ? "全部比赛 AI 实时决策 + AI 复盘" : "All live AI decisions + AI review"}</li>
        <li>{locale === "zh-CN" ? "Email / QQ / 微信实时通知" : "Email / QQ / WeChat realtime alerts"}</li>
        <li>
          {fixedTerm
            ? locale === "zh-CN"
              ? "到期自动关闭权限，不自动续费"
              : "Access expires automatically; no auto-renewal"
            : locale === "zh-CN"
              ? "支持订阅生命周期与客户门户管理"
              : "Recurring lifecycle with customer portal management"}
        </li>
      </ul>
      <div className="billing-methods">
        <Method label="Card" value={offer.payment_methods.card} />
        <Method label="Alipay" value={offer.payment_methods.alipay} />
        <Method label="WeChat Pay" value={offer.payment_methods.wechat_pay} />
      </div>
      <button
        className="billing-checkout-btn"
        type="button"
        disabled={busy}
        onClick={() => (authenticated ? onCheckout(offer.key) : onLogin())}
      >
        {busy
          ? "…"
          : authenticated
            ? locale === "zh-CN"
              ? "进入安全结账"
              : "Continue to secure checkout"
            : locale === "zh-CN"
              ? "登录后购买"
              : "Sign in to buy"}
      </button>
    </article>
  );
}

function Method({ label, value }: { label: string; value: string }) {
  const available = !value.startsWith("not_") && value !== "unavailable";
  return (
    <span className={available ? "billing-method is-available" : "billing-method"}>
      {label} · {available ? (value === "subscription" ? "Recurring" : "One-time") : "—"}
    </span>
  );
}
