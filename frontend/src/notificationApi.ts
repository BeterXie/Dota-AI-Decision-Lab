export type NotificationChannel = "EMAIL" | "QQ" | "WECHAT";

export interface NotificationBinding {
  id: string;
  channel: NotificationChannel;
  label: string | null;
  status: "ACTIVE" | "DISABLED";
  verified_at: string;
  destination: Record<string, string | null>;
  created_at: string;
}

export interface NotificationDelivery {
  id: string;
  channel: NotificationChannel;
  event_type: string;
  status: "PENDING" | "SENDING" | "SENT" | "FAILED" | "EXPIRED" | "CANCELLED";
  attempt_count: number;
  sent_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface NotificationCenterState {
  required_entitlement: "realtime_notifications";
  event_type: "AI_DECISION";
  bindings: NotificationBinding[];
  preferences: Record<NotificationChannel, boolean>;
  recent_deliveries: NotificationDelivery[];
}

export interface PairingCode {
  channel: "QQ" | "WECHAT";
  code: string;
  command: string;
  expires_at: string;
  share_url?: string | null;
  contact_url?: string | null;
  pairing_mode?:
    | "QQ_SHARE_LINK"
    | "QQ_CONTACT_LINK"
    | "WECHAT_CONTACT_LINK"
    | "MANUAL_MESSAGE"
    | string;
}

export interface QrBindingSession {
  channel: "QQ" | "WECHAT";
  session_id: string;
  status:
    | "WAITING"
    | "SCANNED"
    | "NEED_VERIFY_CODE"
    | "BOUND"
    | "COMPLETED"
    | "FAILED"
    | "EXPIRED"
    | "CANCELLED"
    | string;
  qrcode_url?: string | null;
  created_at: string;
  expires_at: string;
  message?: string | null;
  account_id?: string | null;
  user_id?: string | null;
  binding_id?: string | null;
}

export async function fetchNotificationCenter(): Promise<NotificationCenterState> {
  return request<NotificationCenterState>("/api/notifications");
}

export async function bindVerifiedEmail(): Promise<NotificationCenterState> {
  return request<NotificationCenterState>("/api/notifications/bindings/email", {
    method: "POST"
  });
}

export async function createPairingCode(channel: "QQ" | "WECHAT"): Promise<PairingCode> {
  return request<PairingCode>(`/api/notifications/pairing/${channel.toLowerCase()}`, {
    method: "POST"
  });
}

export async function startQrBinding(channel: "QQ" | "WECHAT"): Promise<QrBindingSession> {
  return request<QrBindingSession>(`/api/notifications/qr/${channel.toLowerCase()}/start`, {
    method: "POST"
  });
}

export async function pollQrBinding(
  channel: "QQ" | "WECHAT",
  sessionId: string,
  verifyCode?: string
): Promise<QrBindingSession> {
  return request<QrBindingSession>(
    `/api/notifications/qr/${channel.toLowerCase()}/${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(verifyCode ? { verify_code: verifyCode } : {})
    }
  );
}

export async function cancelQrBinding(
  channel: "QQ" | "WECHAT",
  sessionId: string
): Promise<QrBindingSession> {
  return request<QrBindingSession>(
    `/api/notifications/qr/${channel.toLowerCase()}/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" }
  );
}

export async function setNotificationPreference(
  channel: NotificationChannel,
  enabled: boolean
): Promise<NotificationCenterState> {
  return request<NotificationCenterState>(
    `/api/notifications/preferences/${channel.toLowerCase()}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled })
    }
  );
}

export async function disableNotificationBinding(bindingId: string): Promise<NotificationCenterState> {
  return request<NotificationCenterState>(`/api/notifications/bindings/${bindingId}`, {
    method: "DELETE"
  });
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
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
