export interface RuntimeSettingRecord {
  key: string;
  value: unknown;
  value_type: string;
  category: string;
  description: string | null;
  revision: number;
  updated_by: string | null;
  updated_at: string;
}

export interface RuntimeAiProviderRecord {
  provider: string;
  slot: string;
  enabled: boolean;
  decisions_enabled: boolean;
  base_url: string;
  model: string;
  reasoning_effort: string | null;
  reasoning_supported: boolean;
  timeout_seconds: number;
  api_key_secret_key: string | null;
  secret_configured: boolean;
  revision: number;
  updated_by: string | null;
  updated_at: string;
}

export interface RuntimeConfigPayload {
  settings: RuntimeSettingRecord[];
  ai_providers: RuntimeAiProviderRecord[];
  bootstrap: {
    encrypted_secret_storage_available: boolean;
    admin_email_count: number;
  };
}

export interface RuntimeAuditItem {
  id: string;
  target_key: string;
  category: string;
  operation: string;
  previous_value: unknown;
  new_value: unknown;
  secret_changed: boolean;
  actor: string | null;
  created_at: string;
}

export interface RuntimeAuditPayload {
  items: RuntimeAuditItem[];
}

async function runtimeJson<T>(path: string, init?: RequestInit): Promise<T> {
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
      // Preserve the HTTP status when the backend does not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const fetchRuntimeConfig = () =>
  runtimeJson<RuntimeConfigPayload>("/api/admin/runtime/config");

export const fetchRuntimeAudit = (limit = 12) =>
  runtimeJson<RuntimeAuditPayload>(`/api/admin/runtime/audit?limit=${limit}`);

export const updateRuntimeSetting = (key: string, value: unknown) =>
  runtimeJson<RuntimeSettingRecord>(`/api/admin/runtime/settings/${encodeURIComponent(key)}`, {
    method: "PATCH",
    body: JSON.stringify({ value })
  });

export const updateRuntimeAiProvider = (
  provider: string,
  slot: string,
  changes: Partial<
    Pick<
      RuntimeAiProviderRecord,
      "enabled" | "decisions_enabled" | "base_url" | "model" | "reasoning_effort" | "timeout_seconds"
    >
  >
) =>
  runtimeJson<RuntimeAiProviderRecord>(
    `/api/admin/runtime/ai-providers/${encodeURIComponent(provider)}/${encodeURIComponent(slot)}`,
    {
      method: "PATCH",
      body: JSON.stringify(changes)
    }
  );

export const replaceRuntimeSecret = (key: string, value: string) =>
  runtimeJson<{ key: string; configured: boolean }>(
    `/api/admin/runtime/secrets/${encodeURIComponent(key)}`,
    {
      method: "PUT",
      body: JSON.stringify({ value })
    }
  );
