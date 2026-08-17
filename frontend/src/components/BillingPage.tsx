import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  createBillingCheckout,
  createBillingPortal,
  fetchBillingAccount,
  fetchBillingOffers,
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
  const checkout = useMutation({
    mutationFn: createBillingCheckout,
    onSuccess: ({ checkout_url }) => window.location.assign(checkout_url)
  });
  const portal = useMutation({
    mutationFn: createBillingPortal,
    onSuccess: ({ portal_url }) => window.location.assign(portal_url)
  });

  const activeBilling = account.data?.subscriptions.some(
    (item) => item.access_state === "ACTIVE" || item.provider_status === "active"
  );

  return (
    <main className="billing-page">
      <section className="billing-hero">
        <div>
          <a className="billing-back" href="/">
            ← {locale === "zh-CN" ? "返回比赛" : "Back to matches"}
          </a>
          <div className="billing-eyebrow">DOTA AI DECISION LAB · PRO</div>
          <h1>{locale === "zh-CN" ? "升级 Pro" : "Upgrade to Pro"}</h1>
          <p>
            {locale === "zh-CN"
              ? "一个 Pro 权限同时解锁 AI 实时决策、历史 AI 复盘，以及邮件 / QQ / 微信实时通知。"
              : "One Pro purchase unlocks live AI decisions, historical AI review, and realtime Email / QQ / WeChat alerts."}
          </p>
        </div>
        <div className={`billing-status ${hasPro ? "is-pro" : ""}`}>
          <span>{locale === "zh-CN" ? "当前状态" : "Current access"}</span>
          <strong>{hasPro ? "PRO" : "FREE"}</strong>
        </div>
      </section>

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

          {(checkout.error || portal.error) && (
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
                  ? "月订阅用于支持自动续费的支付方式；微信支付采用 30 / 365 天一次性 Pro 通行证，不伪装成自动续费。最终可用支付方式由 Paddle 在结账时根据地区、币种与账号审批决定。"
                  : "Monthly Pro is for payment methods that support recurring billing. WeChat Pay uses 30 / 365-day one-time passes rather than pretending to auto-renew. Paddle makes the final method decision at checkout based on location, currency, and account approval."}
              </p>
            </div>
            <div>
              <div className="billing-eyebrow">CRYPTO / STABLECOIN</div>
              <h2>{locale === "zh-CN" ? "独立 Provider，默认关闭" : "Separate provider, disabled by default"}</h2>
              <p>
                {locale === "zh-CN"
                  ? "稳定币不会绕过现有账单系统。未来会作为独立 provider 接入同一 entitlement 生命周期，并在上线前单独处理主体、地区、资产网络和合规边界。"
                  : "Stablecoin payments will not bypass this billing system. A future adapter will feed the same entitlement lifecycle with explicit entity, jurisdiction, asset, and network rules."}
              </p>
            </div>
          </section>
        </>
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
      <div className="billing-offer-kind">{fixedTerm ? "ONE-TIME" : "RECURRING"}</div>
      <h2>{title}</h2>
      <p className="billing-price-note">
        {locale === "zh-CN"
          ? "金额、税费与可用币种在 Paddle 安全结账页确认。"
          : "Amount, taxes, and available currency are confirmed in secure Paddle checkout."}
      </p>
      <ul>
        <li>{locale === "zh-CN" ? "AI 实时决策 + AI 复盘" : "Live AI decisions + AI review"}</li>
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
