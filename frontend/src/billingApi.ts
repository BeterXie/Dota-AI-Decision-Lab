export interface BillingOffer {
  key: string;
  label: string;
  kind: "subscription" | "fixed_term";
  grant_days: number | null;
  entitlements: string[];
  payment_methods: {
    card: string;
    alipay: string;
    wechat_pay: string;
  };
}

export interface SeriesPassOffer extends Partial<BillingOffer> {
  enabled: boolean;
  scope_type?: "SERIES";
  access_days?: number;
}

export interface BillingOffersState {
  provider: "paddle";
  enabled: boolean;
  environment: "sandbox" | "live";
  offers: BillingOffer[];
  series_pass: SeriesPassOffer;
  referral: {
    enabled: boolean;
    campaign_key: string;
  };
  local_payment_notes: {
    alipay: string;
    wechat_pay: string;
  };
  crypto: {
    enabled: boolean;
    architecture: string;
    status: string;
  };
}

export interface BillingAccountState {
  entitlements: string[];
  grants: Array<{
    entitlement: string;
    scope_type: string;
    scope_ref: string | null;
    campaign_key: string | null;
    starts_at: string | null;
    expires_at: string | null;
  }>;
  subscriptions: Array<{
    provider: string;
    plan: string;
    access_state: string;
    provider_status: string | null;
    current_period_end: string | null;
    updated_at: string;
    recurring: boolean;
  }>;
  series_passes: Array<{
    provider: string;
    canonical_series_id: string;
    status: string;
    grant_expires_at: string | null;
    completed_at: string | null;
    payment_blocked: boolean;
  }>;
}

export interface ReferralState {
  enabled: boolean;
  campaign_key: string;
  code: string | null;
  claimed_invites: number;
  rewarded_invites: number;
  reward: {
    trigger: string;
    inviter_days: number;
    invited_days: number;
    max_rewards_per_inviter: number;
    claim_window_days: number;
  };
}

export async function fetchBillingOffers(): Promise<BillingOffersState> {
  return billingRequest<BillingOffersState>("/api/billing/offers");
}

export async function fetchBillingAccount(): Promise<BillingAccountState> {
  return billingRequest<BillingAccountState>("/api/billing/account");
}

export async function createBillingCheckout(offerKey: string): Promise<{ checkout_url: string }> {
  return billingRequest<{ checkout_url: string }>(`/api/billing/checkout/${offerKey}`, {
    method: "POST"
  });
}

export async function createSeriesPassCheckout(
  canonicalSeriesId: string
): Promise<{ checkout_url: string }> {
  return billingRequest<{ checkout_url: string }>(
    `/api/billing/series/${encodeURIComponent(canonicalSeriesId)}/checkout`,
    { method: "POST" }
  );
}

export async function createBillingPortal(): Promise<{ portal_url: string }> {
  return billingRequest<{ portal_url: string }>("/api/billing/portal", { method: "POST" });
}

export async function fetchReferral(): Promise<ReferralState> {
  return billingRequest<ReferralState>("/api/promotions/referral");
}

export async function claimReferral(code: string): Promise<{ claimed: boolean; status: string }> {
  return billingRequest<{ claimed: boolean; status: string }>("/api/promotions/referral/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code })
  });
}

async function billingRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload && typeof payload.detail === "string" ? payload.detail : response.statusText;
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}
