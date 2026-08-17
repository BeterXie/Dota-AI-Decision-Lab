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

export interface BillingOffersState {
  provider: "paddle";
  enabled: boolean;
  environment: "sandbox" | "live";
  offers: BillingOffer[];
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
  subscriptions: Array<{
    provider: string;
    plan: string;
    access_state: string;
    provider_status: string | null;
    current_period_end: string | null;
    updated_at: string;
    recurring: boolean;
  }>;
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

export async function createBillingPortal(): Promise<{ portal_url: string }> {
  return billingRequest<{ portal_url: string }>("/api/billing/portal", { method: "POST" });
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
