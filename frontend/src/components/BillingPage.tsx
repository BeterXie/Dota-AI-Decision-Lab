import React from "react";
import { Close, Search } from "@carbon/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMaps, type MapSummary } from "../api";
import {
  claimReferral,
  createEventPassCheckout,
  createSeriesPassCheckout,
  fetchBillingAccount,
  fetchBillingOffers,
  fetchReferral,
  type PassOffer
} from "../billingApi";
import { buildEventSummaries, buildSeriesSummaries } from "../events";
import { useI18n } from "../i18n";
import { UiIcon } from "./VisualIdentity";
import "./billing.css";

type PlanKind = "free" | "series" | "event";
type PlanFeature = { label: string; included: boolean };
type PurchasablePlanKind = Exclude<PlanKind, "free">;
type ScopeOption = {
  id: string;
  label: string;
  detail: string;
  status: string;
  owned: boolean;
};

const ZERO_DECIMAL_CURRENCIES = new Set(["JPY", "KRW", "CLP"]);

export function BillingPage({
  authenticated,
  onLogin
}: {
  authenticated: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const queryClient = useQueryClient();
  const [pickerKind, setPickerKind] = React.useState<PurchasablePlanKind | null>(null);
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
  const scopeCatalog = useQuery({
    queryKey: ["product", "matches"],
    queryFn: fetchMaps,
    enabled: pickerKind !== null,
    staleTime: 15_000,
    retry: 1
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
  const activePasses = account.data?.passes.filter((pass) => pass.status === "ACTIVE") ?? [];
  const pricingUnavailable = Boolean(offers.error || (offers.data && !offers.data.enabled));
  const scopeOptions = React.useMemo(
    () => pickerKind
      ? buildScopeOptions(scopeCatalog.data ?? [], pickerKind, locale, account.data?.grants ?? [])
      : [],
    [account.data?.grants, locale, pickerKind, scopeCatalog.data]
  );

  React.useEffect(() => {
    if (!pickerKind) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPickerKind(null);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [pickerKind]);

  return (
    <div className="billing-page">
      <header className="billing-heading">
        <div className="billing-heading-copy">
          <span className="billing-eyebrow">COMPETITION ACCESS</span>
          <h1>{zh ? "选择你要跟进的赛事范围" : "Choose the competition scope you follow"}</h1>
          <p>
            {zh
              ? "公开内容先体验，进行中的完整 AI 与实时通知按系列赛或赛事范围解锁。"
              : "Explore public analysis first, then access full live AI and alerts for a series or event."}
          </p>
        </div>
        <div className="billing-scope-note">
          <strong>{zh ? "一次购买" : "One-time purchase"}</strong>
          <span>{zh ? "权限跟随所选系列赛或赛事" : "Access follows the selected series or event"}</span>
        </div>
      </header>

      {(selectedSeriesId || selectedEventId) && (
        <section className="billing-selection" aria-live="polite">
          <span className="billing-selection-icon" aria-hidden="true"><UiIcon name="ticket" size={18} /></span>
          <div>
            <strong>
              {selectedSeriesId
                ? (zh ? "已选择当前 BO 系列赛" : "Current BO series selected")
                : (zh ? "已选择当前赛事" : "Current event selected")}
            </strong>
            <p>
              {zh
                ? "对应方案的购买按钮会把权限绑定到这个范围，不按天数过期。"
                : "The matching purchase button binds access to this scope without a time expiry."}
            </p>
          </div>
        </section>
      )}

      {referralCode && (
        <ReferralClaim
          code={referralCode}
          authenticated={authenticated}
          offers={offers.data?.referral.enabled ?? false}
          onLogin={onLogin}
          mutation={referralClaim}
          locale={locale}
        />
      )}

      {pricingUnavailable && (
        <div className="billing-status-message is-error" role="alert">
          <strong>{zh ? "付费方案暂时不可用" : "Paid passes are temporarily unavailable"}</strong>
          <span>{zh ? "Free Access 仍然开放，请稍后再试。" : "Free Access remains available. Please try again later."}</span>
        </div>
      )}

      <section
        className="billing-grid"
        aria-label={zh ? "赛事权限方案" : "Competition access plans"}
        aria-busy={offers.isLoading}
      >
        <PlanCard
          kind="free"
          scope={zh ? "公开访问" : "Public access"}
          title="Free Access"
          price={<FreePrice locale={locale} />}
          description={zh
            ? "用于熟悉 DotaScope 的公开分析能力，不包含实时通知。"
            : "Explore DotaScope's public analysis without realtime notifications."}
          action={<PassAction kind="free" locale={locale} />}
          includedHeading={zh ? "包含" : "Includes"}
          features={zh ? [
            { label: "小组赛 AI 决策", included: true },
            { label: "AI 表现与复盘", included: true },
            { label: "确认赛果后的基础 AI", included: true },
            { label: "付费阶段进行中的完整 AI", included: false },
            { label: "实时通知", included: false }
          ] : [
            { label: "Group-stage AI decisions", included: true },
            { label: "AI Performance and Review", included: true },
            { label: "Core AI after confirmed results", included: true },
            { label: "Full live AI for paid stages", included: false },
            { label: "Realtime notifications", included: false }
          ]}
          finePrint={zh
            ? "无需购买。赛后公开不会创建会员权限，也不会补发实时通知。"
            : "No purchase required. Public post-match access does not create a pass or backfill alerts."}
        />

        <PlanCard
          kind="series"
          scope={zh ? "一个 BO 系列赛" : "One BO series"}
          title="Series Pass"
          recommended={zh ? "推荐入门" : "Recommended"}
          price={<CatalogPrice offer={offers.data?.series_pass} loading={offers.isLoading} locale={locale} testId="series-pass-price" />}
          description={zh
            ? "跟进一场 BO 系列赛，覆盖其中全部地图与赛后完整历史。"
            : "Follow one BO series across every map and retain its complete post-match history."}
          action={(
            <PassAction
              kind="series"
              offer={offers.data?.series_pass}
              targetId={selectedSeriesId}
              owned={hasSelectedSeriesGrant}
              authenticated={authenticated}
              loading={offers.isLoading}
              pending={seriesCheckout.isPending}
              onLogin={onLogin}
              onPurchase={() => selectedSeriesId && seriesCheckout.mutate(selectedSeriesId)}
              onSelect={() => setPickerKind("series")}
              locale={locale}
            />
          )}
          includedHeading={zh ? "包含 Free Access 的全部内容，以及" : "Everything in Free Access, plus"}
          features={zh ? [
            { label: "系列赛进行中的完整 AI 决策", included: true },
            { label: "该系列赛的实时通知", included: true },
            { label: "全部地图的完整决策历史", included: true },
            { label: "银行卡、支付宝与微信支付（符合条件时）", included: true }
          ] : [
            { label: "Full live AI decisions for the series", included: true },
            { label: "Realtime notifications for the series", included: true },
            { label: "Complete decision history for every map", included: true },
            { label: "Card, Alipay and WeChat Pay when eligible", included: true }
          ]}
          finePrint={zh
            ? "权限绑定一个 BO 系列赛，不按天数过期。"
            : "Access is bound to one BO series and does not expire by date."}
        />

        <PlanCard
          kind="event"
          scope={zh ? "一个完整赛事" : "One complete event"}
          title="Event Pass"
          price={<CatalogPrice offer={offers.data?.event_pass} loading={offers.isLoading} locale={locale} testId="event-pass-price" />}
          description={zh
            ? "覆盖同一赛事中的全部系列赛，适合持续跟进完整赛程。"
            : "Cover every series in one event for continuous access across the full schedule."}
          action={(
            <PassAction
              kind="event"
              offer={offers.data?.event_pass}
              targetId={selectedEventId}
              owned={hasSelectedEventGrant}
              authenticated={authenticated}
              loading={offers.isLoading}
              pending={eventCheckout.isPending}
              onLogin={onLogin}
              onPurchase={() => selectedEventId && eventCheckout.mutate(selectedEventId)}
              onSelect={() => setPickerKind("event")}
              locale={locale}
            />
          )}
          includedHeading={zh ? "包含 Free Access 的全部内容，以及" : "Everything in Free Access, plus"}
          features={zh ? [
            { label: "赛事全部系列赛的完整 AI", included: true },
            { label: "赛事范围内的实时通知", included: true },
            { label: "全部系列赛与地图历史", included: true },
            { label: "银行卡、支付宝与微信支付（符合条件时）", included: true }
          ] : [
            { label: "Full AI for every series in the event", included: true },
            { label: "Realtime notifications across the event", included: true },
            { label: "Complete series and map history", included: true },
            { label: "Card, Alipay and WeChat Pay when eligible", included: true }
          ]}
          finePrint={zh
            ? "权限仅绑定一个赛事，不会自动续费。"
            : "Access covers one event only as a one-time purchase."}
        />
      </section>

      <p className="billing-catalog-note">
        <UiIcon name="check" size={14} />
        {zh
          ? "价格来自 Paddle Catalog，最终税费与可用支付方式以结账页为准。"
          : "Prices come from the Paddle Catalog. Final taxes and available methods are confirmed at checkout."}
      </p>

      {(seriesCheckout.error || eventCheckout.error) && (
        <div className="billing-status-message is-error" role="alert">
          <strong>{zh ? "支付请求失败" : "Checkout request failed"}</strong>
          <span>{zh ? "请确认所选范围尚未购买，然后稍后重试。" : "Confirm this scope is still available, then try again."}</span>
        </div>
      )}

      {authenticated && (referral.data?.enabled || activePasses.length > 0) && (
        <section className="billing-support-grid" aria-label={zh ? "账户会员信息" : "Account access information"}>
          {referral.data?.enabled && (
            <article className="billing-support-card">
              <span className="billing-eyebrow">INVITE & EARN</span>
              <h2>{zh ? "邀请好友" : "Invite friends"}</h2>
              <p>{zh
                ? `好友完成首次付费后，双方按活动规则获得奖励。当前已奖励 ${referral.data.rewarded_invites} 人。`
                : `Rewards are issued after a friend's first paid purchase. ${referral.data.rewarded_invites} referrals rewarded.`}</p>
              <code>{referral.data.code ?? "—"}</code>
            </article>
          )}
          {activePasses.length > 0 && (
            <article className="billing-support-card">
              <span className="billing-eyebrow">YOUR PASSES</span>
              <h2>{zh ? "已购买的范围" : "Purchased scopes"}</h2>
              <div className="billing-pass-list">
                {activePasses.map((pass) => (
                  <span key={`${pass.scope_type}:${pass.canonical_event_id ?? pass.canonical_series_id}`}>
                    <UiIcon name="ticket" size={14} />
                    {pass.scope_type === "EVENT" ? "Event Pass" : "Series Pass"}
                  </span>
                ))}
              </div>
            </article>
          )}
        </section>
      )}

      {pickerKind && (
        <ScopePicker
          key={pickerKind}
          kind={pickerKind}
          options={scopeOptions}
          loading={scopeCatalog.isLoading}
          error={Boolean(scopeCatalog.error)}
          offer={pickerKind === "series" ? offers.data?.series_pass : offers.data?.event_pass}
          authenticated={authenticated}
          pending={pickerKind === "series" ? seriesCheckout.isPending : eventCheckout.isPending}
          checkoutError={Boolean(pickerKind === "series" ? seriesCheckout.error : eventCheckout.error)}
          locale={locale}
          onClose={() => setPickerKind(null)}
          onRetry={() => void scopeCatalog.refetch()}
          onLogin={onLogin}
          onPurchase={(scopeId) => {
            if (pickerKind === "series") seriesCheckout.mutate(scopeId);
            else eventCheckout.mutate(scopeId);
          }}
        />
      )}
    </div>
  );
}

function PlanCard({
  kind,
  scope,
  title,
  recommended,
  price,
  description,
  action,
  includedHeading,
  features,
  finePrint
}: {
  kind: PlanKind;
  scope: string;
  title: string;
  recommended?: string;
  price: React.ReactNode;
  description: string;
  action: React.ReactNode;
  includedHeading: string;
  features: PlanFeature[];
  finePrint: string;
}) {
  return (
    <article className={`billing-plan-card${kind === "series" ? " is-featured" : ""}`}>
      {recommended && <span className="billing-recommended">{recommended}</span>}
      <span className="billing-plan-scope">{scope}</span>
      <h2>{title}</h2>
      {price}
      <p className="billing-plan-description">{description}</p>
      {action}
      <h3>{includedHeading}</h3>
      <ul className="billing-feature-list">
        {features.map((feature) => (
          <li className={feature.included ? "is-included" : "is-excluded"} key={feature.label}>
            <span aria-hidden="true">{feature.included ? <UiIcon name="check" size={15} /> : "—"}</span>
            {feature.label}
          </li>
        ))}
      </ul>
      <p className="billing-plan-fineprint">{finePrint}</p>
    </article>
  );
}

function FreePrice({ locale }: { locale: string }) {
  return (
    <div className="billing-plan-price" data-testid="free-price">
      <strong>{new Intl.NumberFormat(locale, { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(0)}</strong>
      <small>{locale === "zh-CN" ? "持续开放" : "Always available"}</small>
    </div>
  );
}

function CatalogPrice({
  offer,
  loading,
  locale,
  testId
}: {
  offer?: PassOffer;
  loading: boolean;
  locale: string;
  testId: string;
}) {
  const formatted = offer?.price ? formatCatalogPrice(offer.price, locale) : null;
  return (
    <div className={`billing-plan-price${loading ? " is-loading" : ""}`} data-testid={testId}>
      <strong>{formatted ?? "—"}</strong>
      <small>{loading
        ? (locale === "zh-CN" ? "正在读取价格" : "Loading price")
        : offer?.enabled
          ? (locale === "zh-CN" ? "一次购买" : "One-time purchase")
          : (locale === "zh-CN" ? "暂未开放" : "Unavailable")}</small>
    </div>
  );
}

function formatCatalogPrice(
  price: NonNullable<PassOffer["price"]>,
  locale: string
): string | null {
  const lowestUnit = Number(price.amount);
  if (!Number.isFinite(lowestUnit)) return null;
  const divisor = ZERO_DECIMAL_CURRENCIES.has(price.currency_code) ? 1 : 100;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: price.currency_code
  }).format(lowestUnit / divisor);
}

function PassAction({
  kind,
  offer,
  targetId,
  owned = false,
  authenticated = false,
  loading = false,
  pending = false,
  onLogin,
  onPurchase,
  onSelect,
  locale
}: {
  kind: PlanKind;
  offer?: PassOffer;
  targetId?: string | null;
  owned?: boolean;
  authenticated?: boolean;
  loading?: boolean;
  pending?: boolean;
  onLogin?: () => void;
  onPurchase?: () => void;
  onSelect?: () => void;
  locale: string;
}) {
  const zh = locale === "zh-CN";
  if (kind === "free") {
    return <button className="billing-plan-action is-secondary" type="button" disabled><UiIcon name="check" size={16} />{zh ? "当前方案" : "Current plan"}</button>;
  }
  if (loading) {
    return <button className="billing-plan-action is-secondary" type="button" disabled>{zh ? "正在读取方案" : "Loading plan"}</button>;
  }
  if (!offer?.enabled || !offer.price) {
    return <button className="billing-plan-action is-secondary" type="button" disabled>{zh ? "暂未开放" : "Unavailable"}</button>;
  }
  if (owned) {
    return <button className="billing-plan-action is-owned" type="button" disabled><UiIcon name="check" size={16} />{zh ? "已拥有当前范围" : "Current scope owned"}</button>;
  }
  if (!targetId) {
    return (
      <button
        className={`billing-plan-action${kind === "series" ? " is-primary" : " is-secondary"}`}
        type="button"
        onClick={onSelect}
      >
        <UiIcon name="ticket" size={16} />
        {kind === "series"
          ? (zh ? "选择一场系列赛" : "Select a BO series")
          : (zh ? "选择一项赛事" : "Select an event")}
      </button>
    );
  }
  return (
    <button
      className={`billing-plan-action${kind === "series" ? " is-primary" : " is-secondary"}`}
      type="button"
      disabled={pending}
      onClick={authenticated ? onPurchase : onLogin}
    >
      <UiIcon name={authenticated ? "ticket" : "user"} size={16} />
      {pending
        ? (zh ? "正在创建结账" : "Creating checkout")
        : !authenticated
          ? (zh ? "登录后购买" : "Sign in to buy")
          : kind === "series"
            ? (zh ? "购买当前系列赛" : "Buy this series")
            : (zh ? "购买当前赛事" : "Buy this event")}
    </button>
  );
}

function ScopePicker({
  kind,
  options,
  loading,
  error,
  offer,
  authenticated,
  pending,
  checkoutError,
  locale,
  onClose,
  onRetry,
  onLogin,
  onPurchase
}: {
  kind: PurchasablePlanKind;
  options: ScopeOption[];
  loading: boolean;
  error: boolean;
  offer?: PassOffer;
  authenticated: boolean;
  pending: boolean;
  checkoutError: boolean;
  locale: string;
  onClose: () => void;
  onRetry: () => void;
  onLogin: () => void;
  onPurchase: (scopeId: string) => void;
}) {
  const zh = locale === "zh-CN";
  const [query, setQuery] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = options.filter((option) =>
    !normalizedQuery || `${option.label} ${option.detail}`.toLocaleLowerCase().includes(normalizedQuery)
  );
  const selected = options.find((option) => option.id === selectedId) ?? null;
  const formattedPrice = offer?.price ? formatCatalogPrice(offer.price, locale) : null;

  return (
    <div className="billing-picker-backdrop" role="presentation">
      <section
        className="billing-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="billing-picker-title"
      >
        <header className="billing-picker-header">
          <div>
            <span className="billing-eyebrow">{kind === "series" ? "SERIES PASS" : "EVENT PASS"}</span>
            <h2 id="billing-picker-title">
              {kind === "series"
                ? (zh ? "选择一场 BO 系列赛" : "Select a BO series")
                : (zh ? "选择一项赛事" : "Select an event")}
            </h2>
            <p>{zh ? `${formattedPrice ?? "—"} · 一次购买` : `${formattedPrice ?? "—"} · One-time purchase`}</p>
          </div>
          <button className="billing-picker-close" type="button" onClick={onClose} title={zh ? "关闭" : "Close"} aria-label={zh ? "关闭" : "Close"} autoFocus>
            <Close size={19} aria-hidden="true" />
          </button>
        </header>

        <label className="billing-picker-search">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={kind === "series"
              ? (zh ? "搜索战队或赛事" : "Search teams or events")
              : (zh ? "搜索赛事" : "Search events")}
          />
        </label>

        <div className="billing-picker-list" role="radiogroup" aria-label={zh ? "可购买范围" : "Purchasable scopes"}>
          {loading ? (
            <div className="billing-picker-state" role="status">{zh ? "正在读取赛事范围…" : "Loading competition scopes…"}</div>
          ) : error ? (
            <div className="billing-picker-state is-error" role="alert">
              <span>{zh ? "赛事范围读取失败。" : "Competition scopes could not be loaded."}</span>
              <button type="button" onClick={onRetry}>{zh ? "重试" : "Retry"}</button>
            </div>
          ) : filtered.length === 0 ? (
            <div className="billing-picker-state">{zh ? "没有符合条件的赛事范围。" : "No matching competition scopes."}</div>
          ) : filtered.map((option) => (
            <button
              className={`billing-picker-option${selectedId === option.id ? " is-selected" : ""}`}
              type="button"
              role="radio"
              aria-checked={selectedId === option.id}
              disabled={option.owned}
              onClick={() => setSelectedId(option.id)}
              key={option.id}
            >
              <span className="billing-picker-radio" aria-hidden="true" />
              <span className="billing-picker-option-copy">
                <strong>{option.label}</strong>
                <small>{option.detail}</small>
              </span>
              <span className={`billing-picker-status${option.owned ? " is-owned" : ""}`}>
                {option.owned ? (zh ? "已拥有" : "Owned") : option.status}
              </span>
            </button>
          ))}
        </div>

        <footer className="billing-picker-footer">
          <div>
            <strong>{selected ? selected.label : (zh ? "尚未选择" : "No scope selected")}</strong>
            <span>{selected ? selected.detail : (zh ? "选择后即可进入 Paddle 安全结账" : "Select a scope to continue to secure Paddle checkout")}</span>
            {checkoutError && <em role="alert">{zh ? "支付请求失败，请重新选择后重试。" : "Checkout failed. Select the scope and try again."}</em>}
          </div>
          <button
            className="billing-picker-purchase"
            type="button"
            disabled={!selected || pending}
            onClick={() => {
              if (!selected) return;
              if (!authenticated) onLogin();
              else onPurchase(selected.id);
            }}
          >
            <UiIcon name={authenticated ? "ticket" : "user"} size={16} />
            {pending
              ? (zh ? "正在创建结账" : "Creating checkout")
              : authenticated
                ? (zh ? `支付 ${formattedPrice ?? ""}` : `Pay ${formattedPrice ?? ""}`)
                : (zh ? "登录后支付" : "Sign in to pay")}
          </button>
        </footer>
      </section>
    </div>
  );
}

function buildScopeOptions(
  matches: MapSummary[],
  kind: PurchasablePlanKind,
  locale: string,
  grants: Array<{ entitlement: string; scope_type: string; scope_ref: string | null }>
): ScopeOption[] {
  const owned = new Set(
    grants
      .filter((grant) => grant.entitlement === "ai_decisions" && grant.scope_type === kind.toUpperCase())
      .map((grant) => grant.scope_ref)
      .filter((scopeRef): scopeRef is string => Boolean(scopeRef))
  );
  const events = buildEventSummaries(matches);
  if (kind === "event") {
    return events
      .filter((event) =>
        Boolean(event.canonicalEventId)
        && (event.status === "LIVE" || event.status === "UPCOMING")
      )
      .map((event) => ({
        id: event.canonicalEventId as string,
        label: event.name,
        detail: locale === "zh-CN"
          ? `${event.seriesCount} 场系列赛 · ${event.teamCount} 支战队`
          : `${event.seriesCount} series · ${event.teamCount} teams`,
        status: eventStatusLabel(event.status, locale),
        owned: owned.has(event.canonicalEventId as string)
      }));
  }
  return events.flatMap((event) =>
    buildSeriesSummaries(event)
      .filter((series) =>
        series.phase === "LIVE"
        || series.phase === "PREMATCH"
        || series.phase === "UNKNOWN"
      )
      .map((series) => ({
        id: series.seriesId,
        label: `${series.teamA?.name || "TBD"} vs ${series.teamB?.name || "TBD"}`,
        detail: [
          event.name,
          series.bestOf ? `BO${series.bestOf}` : null,
          series.scheduledAt ? formatScopeDate(series.scheduledAt, locale) : null
        ].filter(Boolean).join(" · "),
        status: seriesStatusLabel(series.phase, locale),
        owned: owned.has(series.seriesId)
      }))
  ).slice(0, 80);
}

function eventStatusLabel(status: string, locale: string): string {
  if (status === "LIVE") return locale === "zh-CN" ? "进行中" : "Live";
  if (status === "UPCOMING") return locale === "zh-CN" ? "即将开始" : "Upcoming";
  if (status === "SETTLING") return locale === "zh-CN" ? "结算中" : "Settling";
  return locale === "zh-CN" ? "已结束" : "Completed";
}

function seriesStatusLabel(phase: MapSummary["phase"], locale: string): string {
  if (phase === "LIVE") return locale === "zh-CN" ? "进行中" : "Live";
  if (phase === "PREMATCH" || phase === "UNKNOWN") return locale === "zh-CN" ? "即将开始" : "Upcoming";
  if (phase === "AWAITING_RESULT") return locale === "zh-CN" ? "等待赛果" : "Awaiting result";
  return locale === "zh-CN" ? "已结束" : "Completed";
}

function formatScopeDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
}

function ReferralClaim({
  code,
  authenticated,
  offers,
  onLogin,
  mutation,
  locale
}: {
  code: string;
  authenticated: boolean;
  offers: boolean;
  onLogin: () => void;
  mutation: {
    isPending: boolean;
    isSuccess: boolean;
    error: Error | null;
    mutate: (code: string) => void;
  };
  locale: string;
}) {
  const zh = locale === "zh-CN";
  return (
    <section className="billing-referral-claim">
      <div>
        <span className="billing-eyebrow">REFERRAL</span>
        <strong>{zh ? "好友邀请" : "Friend referral"}</strong>
        <p>{zh ? `邀请码 ${code}，首次付费后按活动规则发放奖励。` : `Referral code ${code}. Rewards follow the campaign rules after a first purchase.`}</p>
      </div>
      {!authenticated ? (
        <button type="button" onClick={onLogin}><UiIcon name="user" size={16} />{zh ? "登录后领取" : "Sign in to claim"}</button>
      ) : offers ? (
        <button type="button" disabled={mutation.isPending || mutation.isSuccess} onClick={() => mutation.mutate(code)}>
          <UiIcon name="check" size={16} />
          {mutation.isSuccess ? (zh ? "已领取" : "Claimed") : (zh ? "领取邀请关系" : "Claim referral")}
        </button>
      ) : (
        <span>{zh ? "活动未开放" : "Campaign inactive"}</span>
      )}
      {mutation.error && <div className="billing-referral-error" role="alert">{mutation.error.message}</div>}
    </section>
  );
}
