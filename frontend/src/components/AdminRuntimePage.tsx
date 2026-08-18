import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthSessionState } from "../authApi";
import {
  fetchRuntimeAudit,
  fetchRuntimeConfig,
  replaceRuntimeSecret,
  updateRuntimeAiProvider,
  updateRuntimeSetting,
  type RuntimeAiProviderRecord,
  type RuntimeAuditItem,
  type RuntimeConfigPayload,
  type RuntimeSettingRecord
} from "../runtimeAdminApi";
import { useI18n } from "../i18n";

export type AdminRuntimeSection = "overview" | "auth" | "ai-providers";

interface AdminRuntimePageProps {
  pathname: string;
  session: AuthSessionState | undefined;
  authLoading: boolean;
  onLogin: () => void;
  onLogout: () => Promise<void>;
}

type ToastState = { tone: "success" | "error"; text: string } | null;

const configQueryKey = ["admin", "runtime", "config"] as const;
const auditQueryKey = ["admin", "runtime", "audit"] as const;

export const AdminRuntimePage: React.FC<AdminRuntimePageProps> = ({
  pathname,
  session,
  authLoading,
  onLogin,
  onLogout
}) => {
  const { locale } = useI18n();
  const queryClient = useQueryClient();
  const [toast, setToast] = React.useState<ToastState>(null);
  const [logoutBusy, setLogoutBusy] = React.useState(false);
  const section = sectionFromPath(pathname);
  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);

  const configQuery = useQuery({
    queryKey: configQueryKey,
    queryFn: fetchRuntimeConfig,
    enabled: signedIn,
    retry: false,
    staleTime: 5_000
  });
  const auditQuery = useQuery({
    queryKey: auditQueryKey,
    queryFn: () => fetchRuntimeAudit(12),
    enabled: signedIn,
    retry: false,
    staleTime: 5_000
  });

  const refresh = React.useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: configQueryKey }),
      queryClient.invalidateQueries({ queryKey: auditQueryKey }),
      queryClient.invalidateQueries({ queryKey: ["auth", "session"] })
    ]);
  }, [queryClient]);

  const settingMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      updateRuntimeSetting(key, value)
  });
  const providerMutation = useMutation({
    mutationFn: ({
      provider,
      slot,
      changes
    }: {
      provider: string;
      slot: string;
      changes: Parameters<typeof updateRuntimeAiProvider>[2];
    }) => updateRuntimeAiProvider(provider, slot, changes)
  });
  const secretMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      replaceRuntimeSecret(key, value)
  });

  const applySetting = async (key: string, value: unknown) => {
    setToast(null);
    try {
      await settingMutation.mutateAsync({ key, value });
      await refresh();
      setToast({ tone: "success", text: locale === "zh-CN" ? "配置已更新，后续请求立即使用新设置。" : "Configuration updated. New requests will use it immediately." });
    } catch (error) {
      setToast({ tone: "error", text: errorText(error) });
    }
  };

  const applyProvider = async (
    provider: RuntimeAiProviderRecord,
    changes: Parameters<typeof updateRuntimeAiProvider>[2]
  ) => {
    setToast(null);
    try {
      await providerMutation.mutateAsync({ provider: provider.provider, slot: provider.slot, changes });
      await refresh();
      setToast({ tone: "success", text: locale === "zh-CN" ? "AI 提供商配置已更新，仅影响后续推理请求。" : "AI provider updated. Only subsequent inference requests are affected." });
    } catch (error) {
      setToast({ tone: "error", text: errorText(error) });
    }
  };

  const applySecret = async (key: string, value: string) => {
    setToast(null);
    try {
      await secretMutation.mutateAsync({ key, value });
      await refresh();
      setToast({ tone: "success", text: locale === "zh-CN" ? "密钥已替换并加密保存；页面不会回显密钥内容。" : "Secret replaced and encrypted. The plaintext value will not be displayed." });
    } catch (error) {
      setToast({ tone: "error", text: errorText(error) });
    }
  };

  const handleLogout = async () => {
    if (logoutBusy) return;
    setLogoutBusy(true);
    try {
      await onLogout();
      window.location.assign("/");
    } finally {
      setLogoutBusy(false);
    }
  };

  if (authLoading) return <AdminRuntimeLoading />;

  if (!signedIn) {
    return (
      <AdminRuntimeAccessState
        title={locale === "zh-CN" ? "需要管理员登录" : "Administrator sign-in required"}
        detail={locale === "zh-CN" ? "运行时控制台只允许已认证管理员访问。" : "The runtime control plane is only available to authenticated administrators."}
        actionLabel={locale === "zh-CN" ? "登录" : "Sign in"}
        onAction={onLogin}
      />
    );
  }

  if (configQuery.error) {
    const forbidden = errorText(configQuery.error).includes("runtime configuration admin access required");
    return (
      <AdminRuntimeAccessState
        title={forbidden ? (locale === "zh-CN" ? "没有控制台权限" : "Control-plane access denied") : (locale === "zh-CN" ? "控制台加载失败" : "Control plane failed to load")}
        detail={forbidden ? (locale === "zh-CN" ? "当前账号已登录，但不在 Runtime Admin 白名单中。" : "This account is signed in but is not in the Runtime Admin allowlist.") : errorText(configQuery.error)}
        actionLabel={locale === "zh-CN" ? "返回站点" : "Back to site"}
        onAction={() => window.location.assign("/")}
      />
    );
  }

  if (!configQuery.data) return <AdminRuntimeLoading />;

  const userLabel = session?.user?.display_name || session?.user?.email || "Admin";
  const lastUpdated = latestUpdate(configQuery.data);

  return (
    <div className="admin-runtime-shell">
      <AdminSidebar section={section} locale={locale} />
      <div className="admin-runtime-main">
        <header className="admin-runtime-topbar">
          <div>
            <strong>DOTA AI</strong>
            <span>{locale === "zh-CN" ? "管理控制台" : "Control Plane"}</span>
          </div>
          <div className="admin-runtime-topbar-actions">
            <span className="admin-last-updated">{locale === "zh-CN" ? "最后更新" : "Last updated"}: {formatDateTime(lastUpdated)}</span>
            <button type="button" className="admin-refresh-button" onClick={() => void refresh()} disabled={configQuery.isFetching}>↻ {locale === "zh-CN" ? "刷新" : "Refresh"}</button>
            <a className="admin-site-link" href="/">{locale === "zh-CN" ? "返回站点" : "Back to site"}</a>
            <div className="admin-user-chip">
              <span className="admin-user-avatar">{userLabel.slice(0, 1).toUpperCase()}</span>
              <div><strong>{userLabel}</strong><small>{locale === "zh-CN" ? "管理员" : "Administrator"}</small></div>
              <button type="button" onClick={() => void handleLogout()} disabled={logoutBusy}>{logoutBusy ? "…" : "↪"}</button>
            </div>
          </div>
        </header>

        {toast && <div className={`admin-toast is-${toast.tone}`} role="status">{toast.text}</div>}

        <main className="admin-runtime-content">
          {section === "overview" && (
            <OverviewPage
              config={configQuery.data}
              audit={auditQuery.data?.items ?? []}
              session={session}
              locale={locale}
            />
          )}
          {section === "auth" && (
            <AuthenticationPage
              config={configQuery.data}
              session={session}
              locale={locale}
              busy={settingMutation.isPending || secretMutation.isPending}
              onSetting={applySetting}
              onSecret={applySecret}
            />
          )}
          {section === "ai-providers" && (
            <AiProvidersPage
              config={configQuery.data}
              locale={locale}
              busy={providerMutation.isPending || secretMutation.isPending}
              onProvider={applyProvider}
              onSecret={applySecret}
            />
          )}
        </main>
      </div>
    </div>
  );
};

function AdminSidebar({ section, locale }: { section: AdminRuntimeSection; locale: string }) {
  const groups = [
    {
      label: locale === "zh-CN" ? "仪表盘" : "Dashboard",
      items: [{ key: "overview", href: "/admin/runtime", icon: "⌂", zh: "概览", en: "Overview", enabled: true }]
    },
    {
      label: locale === "zh-CN" ? "认证与用户" : "Identity & users",
      items: [
        { key: "auth", href: "/admin/runtime/auth", icon: "▣", zh: "认证配置", en: "Authentication", enabled: true },
        { key: "users", href: "#", icon: "♙", zh: "用户管理", en: "Users", enabled: false },
        { key: "roles", href: "#", icon: "♙", zh: "角色与权限", en: "Roles & access", enabled: false }
      ]
    },
    {
      label: locale === "zh-CN" ? "AI 与模型" : "AI & models",
      items: [
        { key: "ai-providers", href: "/admin/runtime/ai-providers", icon: "⌘", zh: "AI 提供商", en: "AI Providers", enabled: true },
        { key: "model", href: "#", icon: "◇", zh: "模型配置", en: "Model settings", enabled: false },
        { key: "decision", href: "#", icon: "▧", zh: "AI 决策设置", en: "AI decision policy", enabled: false },
        { key: "limits", href: "#", icon: "◉", zh: "使用配额与限制", en: "Usage & limits", enabled: false }
      ]
    },
    {
      label: locale === "zh-CN" ? "系统配置" : "System",
      items: [
        { key: "features", href: "#", icon: "◐", zh: "功能开关", en: "Feature flags", enabled: false },
        { key: "notifications", href: "#", icon: "♧", zh: "通知配置", en: "Notifications", enabled: false },
        { key: "secrets", href: "#", icon: "◎", zh: "外部服务 / Secrets", en: "External services / Secrets", enabled: false },
        { key: "system", href: "#", icon: "⚙", zh: "系统设置", en: "System settings", enabled: false }
      ]
    },
    {
      label: locale === "zh-CN" ? "审计与日志" : "Audit & logs",
      items: [
        { key: "audit", href: "#", icon: "▤", zh: "配置变更日志", en: "Configuration audit", enabled: false },
        { key: "ops", href: "#", icon: "▥", zh: "操作日志", en: "Operations log", enabled: false }
      ]
    }
  ];

  return (
    <aside className="admin-sidebar">
      <a className="admin-sidebar-brand" href="/admin/runtime">
        <span className="admin-brand-mark">D</span>
        <div><strong>DOTA AI</strong><small>{locale === "zh-CN" ? "管理控制台" : "Control Plane"}</small></div>
      </a>
      <nav aria-label={locale === "zh-CN" ? "后台管理导航" : "Admin navigation"}>
        {groups.map((group) => (
          <section key={group.label} className="admin-nav-group">
            <span className="admin-nav-label">{group.label}</span>
            {group.items.map((item) => item.enabled ? (
              <a key={item.key} href={item.href} className={section === item.key ? "is-active" : undefined}>
                <span aria-hidden="true">{item.icon}</span><strong>{locale === "zh-CN" ? item.zh : item.en}</strong>
              </a>
            ) : (
              <span key={item.key} className="admin-nav-disabled" aria-disabled="true">
                <span aria-hidden="true">{item.icon}</span><strong>{locale === "zh-CN" ? item.zh : item.en}</strong><em>NEXT</em>
              </span>
            ))}
          </section>
        ))}
      </nav>
      <a className="admin-sidebar-collapse" href="/">← {locale === "zh-CN" ? "返回前台" : "Back to product"}</a>
    </aside>
  );
}

function OverviewPage({
  config,
  audit,
  session,
  locale
}: {
  config: RuntimeConfigPayload;
  audit: RuntimeAuditItem[];
  session: AuthSessionState | undefined;
  locale: string;
}) {
  const emailEnabled = settingBool(config, "auth.email.enabled");
  const googleEnabled = settingBool(config, "auth.google.enabled");
  const steamEnabled = settingBool(config, "auth.steam.enabled");
  const enabledAuth = [emailEnabled, googleEnabled, steamEnabled].filter(Boolean).length;
  const enabledProviders = config.ai_providers.filter((provider) => provider.enabled).length;
  const decisionProviders = config.ai_providers.filter((provider) => provider.enabled && provider.decisions_enabled).length;
  const configuredProviderKeys = config.ai_providers.filter((provider) => provider.secret_configured).length;
  const providerCount = config.ai_providers.length;

  return (
    <div className="admin-page-stack">
      <AdminPageHeading
        title={locale === "zh-CN" ? "控制台概览" : "Control plane overview"}
        detail={locale === "zh-CN" ? "查看当前运行时配置、认证入口与 AI 调度状态。所有数据均来自当前数据库配置。" : "Inspect live runtime configuration, authentication entry points and AI scheduling state. All values come from the current database configuration."}
      />

      <section className="admin-metric-grid">
        <MetricCard icon="▣" label={locale === "zh-CN" ? "认证方式" : "Auth methods"} value={`${enabledAuth} / 3`} detail={locale === "zh-CN" ? "当前已启用" : "currently enabled"} tone="blue" />
        <MetricCard icon="⌘" label={locale === "zh-CN" ? "AI 提供商" : "AI providers"} value={`${enabledProviders} / ${providerCount}`} detail={locale === "zh-CN" ? "总开关已开启" : "provider switch enabled"} tone="green" />
        <MetricCard icon="◉" label={locale === "zh-CN" ? "参与决策" : "Decision fan-out"} value={String(decisionProviders)} detail={locale === "zh-CN" ? "新快照会调度这些提供商" : "providers scheduled for new snapshots"} tone="purple" />
        <MetricCard icon="◇" label={locale === "zh-CN" ? "AI Key" : "AI keys"} value={`${configuredProviderKeys} / ${providerCount}`} detail={config.bootstrap.encrypted_secret_storage_available ? (locale === "zh-CN" ? "数据库加密存储可用" : "encrypted DB storage available") : (locale === "zh-CN" ? "当前依赖环境变量或未配置" : "using environment fallback or missing")} tone="orange" />
      </section>

      <div className="admin-overview-grid">
        <section className="admin-panel admin-panel-span-7">
          <PanelHeading title={locale === "zh-CN" ? "认证方式状态" : "Authentication status"} href="/admin/runtime/auth" action={locale === "zh-CN" ? "管理认证" : "Manage auth"} />
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead><tr><th>{locale === "zh-CN" ? "认证方式" : "Method"}</th><th>{locale === "zh-CN" ? "配置开关" : "Configured"}</th><th>{locale === "zh-CN" ? "当前可用" : "Available"}</th><th>{locale === "zh-CN" ? "说明" : "Notes"}</th></tr></thead>
              <tbody>
                <AuthOverviewRow name={locale === "zh-CN" ? "邮箱登录" : "Email login"} icon="✉" enabled={emailEnabled} available={Boolean(session?.providers?.email)} detail={locale === "zh-CN" ? "一次性验证码（OTP）" : "Passwordless OTP"} />
                <AuthOverviewRow name="Google" icon="G" enabled={googleEnabled} available={Boolean(session?.providers?.google)} detail={locale === "zh-CN" ? "OAuth / OpenID Connect" : "OAuth / OpenID Connect"} />
                <AuthOverviewRow name="Steam" icon="S" enabled={steamEnabled} available={Boolean(session?.providers?.steam)} detail={locale === "zh-CN" ? "Steam OpenID" : "Steam OpenID"} />
              </tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel admin-panel-span-5">
          <PanelHeading title={locale === "zh-CN" ? "最近配置变更" : "Recent configuration changes"} />
          <div className="admin-audit-preview">
            {audit.length === 0 ? <EmptyInline text={locale === "zh-CN" ? "暂无配置变更" : "No configuration changes yet"} /> : audit.slice(0, 6).map((item) => (
              <div className="admin-audit-item" key={item.id}>
                <span className={`admin-audit-dot category-${item.category}`} />
                <div><strong>{auditTitle(item, locale)}</strong><small>{item.actor || "system"} · {formatDateTime(item.created_at)}</small></div>
              </div>
            ))}
          </div>
        </section>

        <section className="admin-panel admin-panel-span-8">
          <PanelHeading title={locale === "zh-CN" ? "AI 提供商状态" : "AI provider status"} href="/admin/runtime/ai-providers" action={locale === "zh-CN" ? "管理提供商" : "Manage providers"} />
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead><tr><th>{locale === "zh-CN" ? "提供商" : "Provider"}</th><th>{locale === "zh-CN" ? "总开关" : "Enabled"}</th><th>{locale === "zh-CN" ? "参与决策" : "Decision"}</th><th>{locale === "zh-CN" ? "当前模型" : "Model"}</th><th>{locale === "zh-CN" ? "超时" : "Timeout"}</th><th>API Key</th></tr></thead>
              <tbody>{config.ai_providers.map((provider) => (
                <tr key={`${provider.provider}:${provider.slot}`}>
                  <td><ProviderIdentity provider={provider} /></td>
                  <td><StatusPill enabled={provider.enabled} /></td>
                  <td><StatusPill enabled={provider.decisions_enabled} /></td>
                  <td className="admin-mono">{provider.model}</td>
                  <td>{provider.timeout_seconds}s</td>
                  <td><StatusPill enabled={provider.secret_configured} enabledLabel={locale === "zh-CN" ? "已配置" : "Configured"} disabledLabel={locale === "zh-CN" ? "未配置" : "Missing"} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel admin-panel-span-4">
          <PanelHeading title={locale === "zh-CN" ? "系统信息" : "System information"} />
          <dl className="admin-system-list">
            <div><dt>{locale === "zh-CN" ? "配置存储" : "Configuration store"}</dt><dd>PostgreSQL</dd></div>
            <div><dt>{locale === "zh-CN" ? "Secret 加密" : "Secret encryption"}</dt><dd><StatusPill enabled={config.bootstrap.encrypted_secret_storage_available} enabledLabel={locale === "zh-CN" ? "可用" : "Available"} disabledLabel={locale === "zh-CN" ? "未启用" : "Unavailable"} /></dd></div>
            <div><dt>{locale === "zh-CN" ? "管理员数量" : "Runtime admins"}</dt><dd>{config.bootstrap.admin_email_count}</dd></div>
            <div><dt>{locale === "zh-CN" ? "热更新语义" : "Hot update semantics"}</dt><dd>{locale === "zh-CN" ? "后续请求" : "Subsequent requests"}</dd></div>
            <div><dt>{locale === "zh-CN" ? "AI 请求快照" : "AI request snapshot"}</dt><dd>{locale === "zh-CN" ? "PREPARE 时冻结" : "Frozen at PREPARE"}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}

function AuthenticationPage({
  config,
  session,
  locale,
  busy,
  onSetting,
  onSecret
}: {
  config: RuntimeConfigPayload;
  session: AuthSessionState | undefined;
  locale: string;
  busy: boolean;
  onSetting: (key: string, value: unknown) => Promise<void>;
  onSecret: (key: string, value: string) => Promise<void>;
}) {
  const emailEnabled = settingBool(config, "auth.email.enabled");
  const googleEnabled = settingBool(config, "auth.google.enabled");
  const steamEnabled = settingBool(config, "auth.steam.enabled");
  const clientId = settingString(config, "auth.google.client_id");
  const externalUrl = settingString(config, "auth.external_base_url");
  const googleAvailable = Boolean(session?.providers?.google);
  const steamAvailable = Boolean(session?.providers?.steam);

  return (
    <div className="admin-page-stack">
      <AdminPageHeading
        title={locale === "zh-CN" ? "认证配置" : "Authentication configuration"}
        detail={locale === "zh-CN" ? "管理邮箱、Google 与 Steam 登录。开关和回调配置保存后无需重启服务，后续登录请求立即读取新配置。" : "Manage email, Google and Steam sign-in. Changes apply to subsequent login requests without restarting the service."}
      />

      <div className="admin-detail-grid">
        <div className="admin-detail-main">
          <AuthConfigCard
            icon="✉"
            title={locale === "zh-CN" ? "邮箱登录" : "Email login"}
            detail={locale === "zh-CN" ? "通过邮箱地址发送一次性验证码（OTP）建立真实 session。" : "Send a one-time code (OTP) to establish a real session."}
            enabled={emailEnabled}
            available={Boolean(session?.providers?.email)}
            busy={busy}
            onToggle={(value) => onSetting("auth.email.enabled", value)}
          >
            <div className="admin-auth-facts">
              <Fact label={locale === "zh-CN" ? "验证方式" : "Verification"} value="Passwordless OTP" />
              <Fact label={locale === "zh-CN" ? "会话" : "Session"} value="HttpOnly dota_session" />
              <Fact label={locale === "zh-CN" ? "热更新" : "Hot update"} value={locale === "zh-CN" ? "立即影响后续验证码请求" : "Subsequent OTP requests"} />
            </div>
          </AuthConfigCard>

          <AuthConfigCard
            icon="G"
            title="Google 登录"
            detail={locale === "zh-CN" ? "Google OAuth / OpenID Connect。Client Secret 为只写字段，不会在后台回显。" : "Google OAuth / OpenID Connect. Client Secret is write-only and never echoed by the admin UI."}
            enabled={googleEnabled}
            available={googleAvailable}
            busy={busy}
            onToggle={(value) => onSetting("auth.google.enabled", value)}
          >
            <div className="admin-form-grid two-column">
              <TextSettingEditor label="Client ID" value={clientId} placeholder="123456.apps.googleusercontent.com" busy={busy} onSave={(value) => onSetting("auth.google.client_id", value)} />
              <ReadOnlyField label="Callback URL" value={callbackUrl(externalUrl, "/api/auth/google/callback")} />
              <TextSettingEditor label="External Base URL" value={externalUrl} placeholder="http://127.0.0.1:5173" busy={busy} onSave={(value) => onSetting("auth.external_base_url", value)} />
              <SecretReplaceControl
                label="Client Secret"
                configured={googleAvailable}
                statusDetail={googleEnabled && !googleAvailable ? (locale === "zh-CN" ? "启用中但当前不可用：请检查 Secret / Client ID / Callback URL" : "Enabled but unavailable: verify Secret / Client ID / Callback URL") : undefined}
                busy={busy}
                locale={locale}
                onReplace={(value) => onSecret("auth.google.client_secret", value)}
              />
            </div>
          </AuthConfigCard>

          <AuthConfigCard
            icon="S"
            title="Steam 登录"
            detail={locale === "zh-CN" ? "使用 Steam OpenID，不要求 Steam Web API Key。Realm 与 Callback 从 External Base URL 派生。" : "Uses Steam OpenID and does not require a Steam Web API key. Realm and callback derive from the External Base URL."}
            enabled={steamEnabled}
            available={steamAvailable}
            busy={busy}
            onToggle={(value) => onSetting("auth.steam.enabled", value)}
          >
            <div className="admin-form-grid two-column">
              <ReadOnlyField label="Callback URL" value={callbackUrl(externalUrl, "/api/auth/steam/callback")} />
              <ReadOnlyField label="Realm" value={externalUrl || "—"} />
              <div className="admin-note-card">
                <strong>{locale === "zh-CN" ? "账号身份" : "Account identity"}</strong>
                <span>{locale === "zh-CN" ? "Steam subject 使用稳定 Steam ID；不会伪造邮箱。" : "Steam identity uses the stable Steam ID and never fabricates an email address."}</span>
              </div>
            </div>
          </AuthConfigCard>
        </div>

        <aside className="admin-detail-rail">
          <section className="admin-panel">
            <PanelHeading title={locale === "zh-CN" ? "提供商可用性" : "Provider availability"} />
            <AvailabilityRow icon="✉" label={locale === "zh-CN" ? "邮箱登录" : "Email"} available={Boolean(session?.providers?.email)} />
            <AvailabilityRow icon="G" label="Google" available={googleAvailable} />
            <AvailabilityRow icon="S" label="Steam" available={steamAvailable} />
          </section>
          <section className="admin-panel">
            <PanelHeading title={locale === "zh-CN" ? "运行时语义" : "Runtime semantics"} />
            <div className="admin-guidance-list">
              <span>✓ {locale === "zh-CN" ? "保存后无需重启 backend" : "No backend restart after save"}</span>
              <span>✓ {locale === "zh-CN" ? "Secret 只写、不回显" : "Secrets are write-only"}</span>
              <span>✓ {locale === "zh-CN" ? "所有变更写入审计日志" : "Changes are recorded in the audit log"}</span>
              <span>✓ {locale === "zh-CN" ? "全局 AUTH_ENABLED 仍属于启动级安全边界" : "Global AUTH_ENABLED remains a bootstrap safety boundary"}</span>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function AiProvidersPage({
  config,
  locale,
  busy,
  onProvider,
  onSecret
}: {
  config: RuntimeConfigPayload;
  locale: string;
  busy: boolean;
  onProvider: (provider: RuntimeAiProviderRecord, changes: Parameters<typeof updateRuntimeAiProvider>[2]) => Promise<void>;
  onSecret: (key: string, value: string) => Promise<void>;
}) {
  const [editing, setEditing] = React.useState<string | null>(null);
  const enabled = config.ai_providers.filter((provider) => provider.enabled).length;
  const decision = config.ai_providers.filter((provider) => provider.enabled && provider.decisions_enabled).length;
  const keyed = config.ai_providers.filter((provider) => provider.secret_configured).length;

  return (
    <div className="admin-page-stack">
      <AdminPageHeading
        title={locale === "zh-CN" ? "AI 提供商" : "AI Providers"}
        detail={locale === "zh-CN" ? "管理运行时 provider、模型、Base URL、超时、思考强度与 API Key。修改只影响后续请求；已进入 PREPARE 的请求继续使用冻结快照。" : "Manage runtime providers, models, base URLs, timeouts, reasoning effort and API keys. Edits affect only subsequent requests; requests already in PREPARE keep their frozen snapshot."}
      />

      <div className="admin-provider-summary">
        <SummaryChip label={locale === "zh-CN" ? "启用中" : "Enabled"} value={`${enabled}`} tone="green" />
        <SummaryChip label={locale === "zh-CN" ? "参与决策" : "Decision fan-out"} value={`${decision}`} tone="blue" />
        <SummaryChip label={locale === "zh-CN" ? "已配置 Key" : "Keys configured"} value={`${keyed}/${config.ai_providers.length}`} tone="purple" />
        <div className="admin-provider-snapshot-note">◉ {locale === "zh-CN" ? "单次推理在 PREPARE 时冻结 provider / model / key / timeout / reasoning" : "Each inference freezes provider / model / key / timeout / reasoning at PREPARE"}</div>
      </div>

      <section className="admin-panel admin-provider-panel">
        <div className="admin-panel-toolbar">
          <PanelHeading title={locale === "zh-CN" ? "提供商管理" : "Provider management"} />
          <button className="admin-secondary-button" type="button" disabled title={locale === "zh-CN" ? "第一批先管理现有 provider slots；自定义 slot 下一批开放。" : "The first batch manages existing provider slots; custom slots come next."}>＋ {locale === "zh-CN" ? "新增提供商" : "Add provider"}</button>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table admin-provider-table">
            <thead><tr><th>{locale === "zh-CN" ? "提供商" : "Provider"}</th><th>{locale === "zh-CN" ? "总开关" : "Enabled"}</th><th>{locale === "zh-CN" ? "参与决策" : "Decision"}</th><th>{locale === "zh-CN" ? "当前模型" : "Model"}</th><th>Base URL</th><th>{locale === "zh-CN" ? "超时" : "Timeout"}</th><th>{locale === "zh-CN" ? "思考强度" : "Reasoning"}</th><th>API Key</th><th>{locale === "zh-CN" ? "操作" : "Action"}</th></tr></thead>
            <tbody>
              {config.ai_providers.map((provider) => {
                const key = `${provider.provider}:${provider.slot}`;
                const isEditing = editing === key;
                return (
                  <React.Fragment key={key}>
                    <tr>
                      <td><ProviderIdentity provider={provider} /></td>
                      <td><RuntimeToggle checked={provider.enabled} disabled={busy} label={`${provider.provider} enabled`} onChange={(value) => void onProvider(provider, { enabled: value })} /></td>
                      <td><RuntimeToggle checked={provider.decisions_enabled} disabled={busy || !provider.enabled} label={`${provider.provider} decisions`} onChange={(value) => void onProvider(provider, { decisions_enabled: value })} /></td>
                      <td className="admin-mono">{provider.model}</td>
                      <td className="admin-url-cell">{provider.base_url}</td>
                      <td>{provider.timeout_seconds}s</td>
                      <td>{provider.reasoning_supported ? <ReasoningPill value={provider.reasoning_effort} /> : <span className="admin-muted">—</span>}</td>
                      <td><StatusPill enabled={provider.secret_configured} enabledLabel={locale === "zh-CN" ? "已配置" : "Configured"} disabledLabel={locale === "zh-CN" ? "未配置" : "Missing"} /></td>
                      <td><button className="admin-link-button" type="button" onClick={() => setEditing(isEditing ? null : key)}>{isEditing ? (locale === "zh-CN" ? "收起" : "Close") : (locale === "zh-CN" ? "编辑" : "Edit")}</button></td>
                    </tr>
                    {isEditing && (
                      <tr className="admin-provider-editor-row"><td colSpan={9}>
                        <ProviderEditor provider={provider} locale={locale} busy={busy} onSave={(changes) => onProvider(provider, changes)} onSecret={onSecret} />
                      </td></tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="admin-panel-footnote">ⓘ {locale === "zh-CN" ? "关闭“总开关”后该提供商不会被新请求解析；关闭“参与决策”只会移出新快照的 AI fan-out。" : "Disabling the provider prevents new resolution. Disabling decision fan-out only removes it from new snapshot scheduling."}</div>
      </section>
    </div>
  );
}

function ProviderEditor({
  provider,
  locale,
  busy,
  onSave,
  onSecret
}: {
  provider: RuntimeAiProviderRecord;
  locale: string;
  busy: boolean;
  onSave: (changes: Parameters<typeof updateRuntimeAiProvider>[2]) => Promise<void>;
  onSecret: (key: string, value: string) => Promise<void>;
}) {
  const [model, setModel] = React.useState(provider.model);
  const [baseUrl, setBaseUrl] = React.useState(provider.base_url);
  const [timeout, setTimeout] = React.useState(String(provider.timeout_seconds));
  const [reasoning, setReasoning] = React.useState(provider.reasoning_effort ?? "medium");

  React.useEffect(() => {
    setModel(provider.model);
    setBaseUrl(provider.base_url);
    setTimeout(String(provider.timeout_seconds));
    setReasoning(provider.reasoning_effort ?? "medium");
  }, [provider]);

  const save = async () => {
    const timeoutNumber = Number(timeout);
    if (!model.trim() || !baseUrl.trim() || !Number.isFinite(timeoutNumber)) return;
    await onSave({
      model: model.trim(),
      base_url: baseUrl.trim(),
      timeout_seconds: timeoutNumber,
      ...(provider.reasoning_supported ? { reasoning_effort: reasoning } : {})
    });
  };

  return (
    <div className="admin-provider-editor">
      <div className="admin-form-grid provider-editor-grid">
        <label className="admin-field"><span>Model</span><input value={model} onChange={(event) => setModel(event.target.value)} disabled={busy} /></label>
        <label className="admin-field"><span>Base URL</span><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} disabled={busy} /></label>
        <label className="admin-field"><span>{locale === "zh-CN" ? "超时（秒）" : "Timeout (seconds)"}</span><input type="number" min="1" max="300" value={timeout} onChange={(event) => setTimeout(event.target.value)} disabled={busy} /></label>
        {provider.reasoning_supported && (
          <label className="admin-field"><span>{locale === "zh-CN" ? "思考强度" : "Reasoning effort"}</span><select value={reasoning} onChange={(event) => setReasoning(event.target.value)} disabled={busy}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
        )}
      </div>
      <div className="admin-provider-editor-actions">
        {provider.api_key_secret_key && <SecretReplaceControl label="API Key" configured={provider.secret_configured} locale={locale} busy={busy} compact onReplace={(value) => onSecret(provider.api_key_secret_key!, value)} />}
        <button type="button" className="admin-primary-button" disabled={busy || !model.trim() || !baseUrl.trim()} onClick={() => void save()}>{busy ? "…" : locale === "zh-CN" ? "保存提供商配置" : "Save provider configuration"}</button>
      </div>
    </div>
  );
}

function AuthConfigCard({
  icon,
  title,
  detail,
  enabled,
  available,
  busy,
  onToggle,
  children
}: {
  icon: string;
  title: string;
  detail: string;
  enabled: boolean;
  available: boolean;
  busy: boolean;
  onToggle: (value: boolean) => Promise<void>;
  children: React.ReactNode;
}) {
  return (
    <section className="admin-panel admin-auth-card">
      <div className="admin-auth-card-head">
        <span className="admin-auth-icon">{icon}</span>
        <div><div className="admin-auth-title-row"><h2>{title}</h2><StatusPill enabled={enabled} /></div><p>{detail}</p></div>
        <div className="admin-auth-toggle-wrap"><span className={`admin-health-dot ${available ? "is-up" : "is-down"}`}>{available ? "●" : "●"}</span><RuntimeToggle checked={enabled} disabled={busy} label={`${title} enabled`} onChange={(value) => void onToggle(value)} /></div>
      </div>
      <div className="admin-auth-card-body">{children}</div>
    </section>
  );
}

function TextSettingEditor({ label, value, placeholder, busy, onSave }: { label: string; value: string; placeholder: string; busy: boolean; onSave: (value: string) => Promise<void> }) {
  const [draft, setDraft] = React.useState(value);
  React.useEffect(() => setDraft(value), [value]);
  const changed = draft.trim() !== value;
  return (
    <label className="admin-field"><span>{label}</span><div className="admin-inline-field"><input value={draft} placeholder={placeholder} onChange={(event) => setDraft(event.target.value)} disabled={busy} /><button type="button" disabled={busy || !changed || !draft.trim()} onClick={() => void onSave(draft.trim())}>{changed ? "Save" : "✓"}</button></div></label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return <label className="admin-field"><span>{label}</span><input value={value || "—"} readOnly className="is-readonly" /></label>;
}

function SecretReplaceControl({
  label,
  configured,
  locale,
  busy,
  compact = false,
  statusDetail,
  onReplace
}: {
  label: string;
  configured: boolean;
  locale: string;
  busy: boolean;
  compact?: boolean;
  statusDetail?: string;
  onReplace: (value: string) => Promise<void>;
}) {
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState("");
  const submit = async () => {
    if (!value) return;
    await onReplace(value);
    setValue("");
    setEditing(false);
  };
  return (
    <div className={`admin-secret-control ${compact ? "is-compact" : ""}`}>
      <div className="admin-secret-head"><span>{label}</span><StatusPill enabled={configured} enabledLabel={locale === "zh-CN" ? "已配置" : "Configured"} disabledLabel={locale === "zh-CN" ? "未验证 / 未配置" : "Unverified / missing"} /></div>
      {statusDetail && <small>{statusDetail}</small>}
      {editing ? (
        <div className="admin-secret-editor"><input type="password" autoComplete="new-password" placeholder={locale === "zh-CN" ? "输入新密钥（保存后不会回显）" : "Enter a new secret (never echoed after save)"} value={value} onChange={(event) => setValue(event.target.value)} disabled={busy} /><button className="admin-primary-button" type="button" disabled={busy || !value} onClick={() => void submit()}>{locale === "zh-CN" ? "保存" : "Save"}</button><button className="admin-secondary-button" type="button" disabled={busy} onClick={() => { setEditing(false); setValue(""); }}>{locale === "zh-CN" ? "取消" : "Cancel"}</button></div>
      ) : (
        <button type="button" className="admin-secondary-button" disabled={busy} onClick={() => setEditing(true)}>{configured ? (locale === "zh-CN" ? "替换" : "Replace") : (locale === "zh-CN" ? "配置" : "Configure")}</button>
      )}
    </div>
  );
}

function RuntimeToggle({ checked, disabled, label, onChange }: { checked: boolean; disabled?: boolean; label: string; onChange: (value: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`admin-toggle ${checked ? "is-on" : ""}`} disabled={disabled} onClick={() => onChange(!checked)}><span /></button>;
}

function MetricCard({ icon, label, value, detail, tone }: { icon: string; label: string; value: string; detail: string; tone: string }) {
  return <article className={`admin-metric-card tone-${tone}`}><span className="admin-metric-icon">{icon}</span><div><small>{label}</small><strong>{value}</strong><span>{detail}</span></div><i aria-hidden="true" /></article>;
}

function SummaryChip({ label, value, tone }: { label: string; value: string; tone: string }) {
  return <div className={`admin-summary-chip tone-${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function PanelHeading({ title, href, action }: { title: string; href?: string; action?: string }) {
  return <div className="admin-panel-heading"><h2>{title}</h2>{href && action ? <a href={href}>{action} ›</a> : null}</div>;
}

function AdminPageHeading({ title, detail }: { title: string; detail: string }) {
  return <header className="admin-page-heading"><h1>{title}</h1><p>{detail}</p></header>;
}

function StatusPill({ enabled, enabledLabel = "Enabled", disabledLabel = "Disabled" }: { enabled: boolean; enabledLabel?: string; disabledLabel?: string }) {
  return <span className={`admin-status-pill ${enabled ? "is-enabled" : "is-disabled"}`}>{enabled ? enabledLabel : disabledLabel}</span>;
}

function ReasoningPill({ value }: { value: string | null }) {
  const normalized = value || "—";
  return <span className={`admin-reasoning-pill is-${normalized}`}>{normalized}</span>;
}

function ProviderIdentity({ provider }: { provider: RuntimeAiProviderRecord }) {
  const initials: Record<string, string> = { openai: "◎", local_openai: "▤", anthropic: "A", gemini: "✦", deepseek: "D", kimi: "K" };
  const labels: Record<string, string> = { openai: "OpenAI", local_openai: "Local OpenAI", anthropic: "Anthropic", gemini: "Gemini", deepseek: "DeepSeek", kimi: "Kimi" };
  return <div className={`admin-provider-identity provider-${provider.provider}`}><span>{initials[provider.provider] || provider.provider.slice(0, 1).toUpperCase()}</span><div><strong>{labels[provider.provider] || provider.provider}</strong>{provider.slot !== "default" && <small>{provider.slot}</small>}</div></div>;
}

function AuthOverviewRow({ name, icon, enabled, available, detail }: { name: string; icon: string; enabled: boolean; available: boolean; detail: string }) {
  return <tr><td><div className="admin-provider-identity"><span>{icon}</span><strong>{name}</strong></div></td><td><StatusPill enabled={enabled} /></td><td><StatusPill enabled={available} enabledLabel="Ready" disabledLabel="Unavailable" /></td><td>{detail}</td></tr>;
}

function AvailabilityRow({ icon, label, available }: { icon: string; label: string; available: boolean }) {
  return <div className="admin-availability-row"><span className="admin-auth-icon is-small">{icon}</span><strong>{label}</strong><StatusPill enabled={available} enabledLabel="Ready" disabledLabel="Unavailable" /></div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="admin-fact"><span>{label}</span><strong>{value}</strong></div>;
}

function EmptyInline({ text }: { text: string }) {
  return <div className="admin-empty-inline">{text}</div>;
}

function AdminRuntimeLoading() {
  return <div className="admin-runtime-loading"><span className="admin-loading-mark">D</span><strong>Loading runtime control plane…</strong></div>;
}

function AdminRuntimeAccessState({ title, detail, actionLabel, onAction }: { title: string; detail: string; actionLabel: string; onAction: () => void }) {
  return <div className="admin-access-state"><div className="admin-access-card"><span className="admin-loading-mark">D</span><h1>{title}</h1><p>{detail}</p><button type="button" className="admin-primary-button" onClick={onAction}>{actionLabel}</button></div></div>;
}

function setting(config: RuntimeConfigPayload, key: string): RuntimeSettingRecord | undefined {
  return config.settings.find((item) => item.key === key);
}

function settingBool(config: RuntimeConfigPayload, key: string): boolean {
  return Boolean(setting(config, key)?.value);
}

function settingString(config: RuntimeConfigPayload, key: string): string {
  const value = setting(config, key)?.value;
  return typeof value === "string" ? value : "";
}

function callbackUrl(base: string, path: string): string {
  return base ? `${base.replace(/\/$/, "")}${path}` : "—";
}

function latestUpdate(config: RuntimeConfigPayload): string | null {
  const values = [
    ...config.settings.map((item) => item.updated_at),
    ...config.ai_providers.map((item) => item.updated_at)
  ].filter(Boolean).sort();
  return values.length ? values[values.length - 1] : null;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

function auditTitle(item: RuntimeAuditItem, locale: string): string {
  if (item.secret_changed) return locale === "zh-CN" ? `替换 ${item.target_key}` : `Replaced ${item.target_key}`;
  if (item.target_key.startsWith("ai_provider:")) return locale === "zh-CN" ? `更新 ${item.target_key.replace("ai_provider:", "")}` : `Updated ${item.target_key.replace("ai_provider:", "")}`;
  return locale === "zh-CN" ? `更新 ${item.target_key}` : `Updated ${item.target_key}`;
}

function sectionFromPath(pathname: string): AdminRuntimeSection {
  if (pathname === "/admin/runtime/auth" || pathname.startsWith("/admin/runtime/auth/")) return "auth";
  if (pathname === "/admin/runtime/ai-providers" || pathname.startsWith("/admin/runtime/ai-providers/")) return "ai-providers";
  return "overview";
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
