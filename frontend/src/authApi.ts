export interface AuthUser {
  id: string;
  email: string;
  email_verified_at: string;
  created_at: string;
}

export interface AccessGrant {
  entitlement: string;
  scope_type: "GLOBAL" | "SERIES" | "MAP" | string;
  scope_ref: string | null;
  campaign_key: string | null;
  starts_at: string | null;
  expires_at: string | null;
}

export interface AuthSessionState {
  enabled: boolean;
  authenticated: boolean;
  user: AuthUser | null;
  /** Site-wide/global entitlements only. */
  entitlements: string[];
  /** Includes GLOBAL plus resource-scoped SERIES/MAP grants. */
  grants: AccessGrant[];
}

export interface LoginCodeRequestResult {
  accepted: boolean;
  sent: boolean;
  retry_after_seconds: number;
}

async function authJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail) detail = payload.detail;
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const fetchAuthSession = () => authJson<AuthSessionState>("/api/auth/session");

export const requestLoginCode = (email: string) =>
  authJson<LoginCodeRequestResult>("/api/auth/request-code", {
    method: "POST",
    body: JSON.stringify({ email })
  });

export const verifyLoginCode = (email: string, code: string) =>
  authJson<AuthSessionState>("/api/auth/verify-code", {
    method: "POST",
    body: JSON.stringify({ email, code })
  });

export const logout = () =>
  authJson<{ ok: boolean }>("/api/auth/logout", {
    method: "POST"
  });
