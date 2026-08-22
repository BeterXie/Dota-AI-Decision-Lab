import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthSessionState } from "../authApi";
import {
  fetchRuntimeAudit,
  fetchRuntimeConfig,
  fetchRuntimePolicy,
  fetchRuntimeSecrets,
  replaceRuntimeSecret,
  updateRuntimeAiProvider,
  updateRuntimePolicySetting,
  updateRuntimeSetting,
  type RuntimeAiProviderRecord,
  type RuntimeAuditItem,
  type RuntimeConfigPayload,
  type RuntimeLifecycleFeature,
  type RuntimePolicyPayload,
  type RuntimeSecretStatus,
  type RuntimeSettingRecord
} from "../runtimeAdminApi";
import { useI18n } from "../i18n";

export type AdminRuntimeSection =
  | "overview"
  | "auth"
  | "ai-providers"
  | "ai-decisions"
  | "features"
  | "secrets";

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
const policyQueryKey = ["admin", "runtime", "policy"] as const;
const secretsQueryKey = ["admin", "runtime", "secrets"] as const;

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
    queryFn: () => fetchRuntimeAudit(16),
    enabled: signedIn,
    retry: false,
    staleTime: 5_000
  });
  const policyQuery = useQuery({
    queryKey: policyQueryKey,
    queryFn: fetchRuntimePolicy,
    enabled: signedIn,
    retry: false,
    staleTime: 5_000
  });
  const secretsQuery = useQuery({
    queryKey: secretsQueryKey,
    queryFn: fetchRuntimeSecrets,
    enabled: signedIn,
    retry: false,
    staleTime: 5_000
  });

  const refresh = React.useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: configQueryKey }),
      queryClient.invalidateQueries({ queryKey: auditQueryKey }),
      queryClient.invalidateQueries({ queryKey: policyQueryKey }),
      queryClient.invalidateQueries({ queryKey: secretsQueryKey }),
      queryClient.invalidateQueries({ queryKey: ["auth", "session"] })
    ]);
  }, [queryClient]);

  const settingMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) => updateRuntimeSetting(key, value)
  });
  const policyMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) => updateRuntimePolicySetting(key, value)
  });
  const providerMutation = useMutation({
    mutationFn: ({ provider, slot, changes }: { provider: string; slot: string; changes: Parameters<typeof updateRuntimeAiProvider>[2] }) =>
      updateRuntimeAiProvider(provider, slot, changes)
  });
  const secretMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => replaceRuntimeSecret(key, value)
  });

  const applySetting = async (key: string, value: unknown) => {
    setToast(null);
    try {
      await settingMutation.mutateAsync({ key, value });
      await refresh();
      setToast({ tone: "success", text: locale === "zh-CN" ? "配置已更新，后续请求立即使用新设置。" : "Configuration updated. New requests use it immediately." });
    } catch (error) {
      setToast({ tone: "error", text: errorText(error) });
    }
  };

  const applyPolicy = async (key: string, value: unknown) => {
    setToast(null);
    try {
      await policyMutation.mutateAsync({ key, value });
      await refresh();
      setToast({ tone: "success", text: locale === "zh-CN" ? "运行时策略已更新；正在执行中的请求保持冻结配置。" : "Runtime policy updated; in-flight requests keep their frozen configuration." });
    } catch (error) {
      setToast({ tone: "error", text: errorText(error) });
    }
  };

  const applyProvider = async (provider: RuntimeAiProviderRecord, changes: Parameters<typeof updateRuntimeAiProvider>[2]) => {
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
      setToast({ tone: "success", text: locale === "zh-CN" ? "密钥已替换并加密保存；页面不会回显密钥内容。" : "Secret replaced and encrypted. Plaintext will not be displayed." });
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
    if (session?.enabled === false) {
      return <AdminRuntimeAccessState title={zh(locale, "认证服务未启用", "Authentication is disabled")} detail={zh(locale, "运行时控制台需要启动时启用全局认证；请设置 AUTH_ENABLED=true 并重启服务。", "The runtime control plane requires global authentication at startup. Set AUTH_ENABLED=true and restart the service.")} />;
    }
    return <AdminRuntimeAccessState title={zh(locale, "需要管理员登录", "Administrator sign-in required")} detail={zh(locale, "运行时控制台只允许已认证管理员访问。", "The runtime control plane is restricted to authenticated administrators.")} actionLabel={zh(locale, "登录", "Sign in")} onAction={onLogin} />;
  }

  const blockingError = configQuery.error || policyQuery.error || secretsQuery.error;
  if (blockingError) {
    const message = errorText(blockingError);
    const forbidden = message.includes("runtime configuration admin access required");
    return <AdminRuntimeAccessState title={forbidden ? zh(locale, "没有控制台权限", "Control-plane access denied") : zh(locale, "控制台加载失败", "Control plane failed to load")} detail={forbidden ? zh(locale, "当前账号已登录，但不在 Runtime Admin 白名单中。", "This signed-in account is not in the Runtime Admin allowlist.") : message} actionLabel={zh(locale, "返回站点", "Back to site")} onAction={() => window.location.assign("/")} />;
  }

  if (!configQuery.data || !policyQuery.data || !secretsQuery.data) return <AdminRuntimeLoading />;

  const userLabel = session?.user?.display_name || session?.user?.email || "Admin";
  const lastUpdated = latestUpdate(configQuery.data, policyQuery.data);
  const commonBusy = settingMutation.isPending || policyMutation.isPending || providerMutation.isPending || secretMutation.isPending;

  return (
    <div className="admin-runtime-shell">
      <AdminSidebar section={section} locale={locale} />
      <div className="admin-runtime-main">
        <header className="admin-runtime-topbar">
          <div><strong>DOTA AI</strong><span>{zh(locale, "管理控制台", "Control Plane")}</span></div>
          <div className="admin-runtime-topbar-actions">
            <span className="admin-last-updated">{zh(locale, "最后更新", "Last updated")}: {formatDateTime(lastUpdated)}</span>
            <button type="button" className="admin-refresh-button" onClick={() => void refresh()} disabled={configQuery.isFetching || policyQuery.isFetching}>↻ {zh(locale, "刷新", "Refresh")}</button>
            <a className="admin-site-link" href="/">{zh(locale, "返回站点", "Back to site")}</a>
            <div className="admin-user-chip">
              <span className="admin-user-avatar">{userLabel.slice(0, 1).toUpperCase()}</span>
              <div><strong>{userLabel}</strong><small>{zh(locale, "管理员", "Administrator")}</small></div>
              <button type="button" onClick={() => void handleLogout()} disabled={logoutBusy}>{logoutBusy ? "…" : "↪"}</button>
            </div>
          </div>
        </header>
        {toast && <div className={`admin-toast is-${toast.tone}`} role="status">{toast.text}</div>}
        <main className="admin-runtime-content">
          {section === "overview" && <OverviewPage config={configQuery.data} policy={policyQuery.data} secrets={secretsQuery.data.items} audit={auditQuery.data?.items ?? []} locale={locale} globalAuthEnabled={Boolean(session?.enabled)} />}
          {section === "auth" && <AuthenticationPage config={configQuery.data} secrets={secretsQuery.data.items} globalAuthEnabled={Boolean(session?.enabled)} locale={locale} busy={commonBusy} onSetting={applySetting} onSecret={applySecret} />}
          {section === "ai-providers" && <AiProvidersPage config={configQuery.data} secrets={secretsQuery.data.items} locale={locale} busy={commonBusy} onProvider={applyProvider} onSecret={applySecret} />}
          {section === "ai-decisions" && <AiDecisionSettingsPage config={configQuery.data} policy={policyQuery.data} locale={locale} busy={commonBusy} onPolicy={applyPolicy} />}
          {section === "features" && <FeatureFlagsPage policy={policyQuery.data} locale={locale} busy={commonBusy} onPolicy={applyPolicy} />}
          {section === "secrets" && <SecretsPage secrets={secretsQuery.data.items} encryptedStorage={configQuery.data.bootstrap.encrypted_secret_storage_available} locale={locale} busy={commonBusy} onSecret={applySecret} />}
        </main>
      </div>
    </div>
  );
};

function AdminSidebar({ section, locale }: { section: AdminRuntimeSection; locale: string }) {
  const groups = [
    { label: zh(locale, "仪表盘", "Dashboard"), items: [{ key: "overview", href: "/admin/runtime", icon: "⌂", zh: "概览", en: "Overview", enabled: true }] },
    { label: zh(locale, "认证与用户", "Identity & users"), items: [
      { key: "auth", href: "/admin/runtime/auth", icon: "▣", zh: "认证配置", en: "Authentication", enabled: true },
      { key: "users", href: "#", icon: "♙", zh: "用户管理", en: "Users", enabled: false },
      { key: "roles", href: "#", icon: "♙", zh: "角色与权限", en: "Roles & access", enabled: false }
    ] },
    { label: zh(locale, "AI 与模型", "AI & models"), items: [
      { key: "ai-providers", href: "/admin/runtime/ai-providers", icon: "⌘", zh: "AI 提供商", en: "AI Providers", enabled: true },
      { key: "model", href: "#", icon: "◇", zh: "模型配置", en: "Model settings", enabled: false },
      { key: "ai-decisions", href: "/admin/runtime/ai-decisions", icon: "▧", zh: "AI 决策设置", en: "AI decision policy", enabled: true },
      { key: "limits", href: "#", icon: "◉", zh: "使用配额与限制", en: "Usage & limits", enabled: false }
    ] },
    { label: zh(locale, "系统配置", "System"), items: [
      { key: "features", href: "/admin/runtime/features", icon: "◐", zh: "功能开关", en: "Feature flags", enabled: true },
      { key: "notifications", href: "#", icon: "♧", zh: "通知配置", en: "Notifications", enabled: false },
      { key: "secrets", href: "/admin/runtime/secrets", icon: "◎", zh: "外部服务 / Secrets", en: "External services / Secrets", enabled: true },
      { key: "system", href: "#", icon: "⚙", zh: "系统设置", en: "System settings", enabled: false }
    ] },
    { label: zh(locale, "审计与日志", "Audit & logs"), items: [
      { key: "audit", href: "#", icon: "▤", zh: "配置变更日志", en: "Configuration audit", enabled: false },
      { key: "ops", href: "#", icon: "▥", zh: "操作日志", en: "Operations log", enabled: false }
    ] }
  ];
  return (
    <aside className="admin-sidebar">
      <a className="admin-sidebar-brand" href="/admin/runtime"><span className="admin-brand-mark">D</span><div><strong>DOTA AI</strong><small>{zh(locale, "管理控制台", "Control Plane")}</small></div></a>
      <nav aria-label={zh(locale, "后台管理导航", "Admin navigation")}>
        {groups.map((group) => <section key={group.label} className="admin-nav-group">
          <span className="admin-nav-label">{group.label}</span>
          {group.items.map((item) => item.enabled ? <a key={item.key} href={item.href} className={section === item.key ? "is-active" : undefined}><span aria-hidden="true">{item.icon}</span><strong>{locale === "zh-CN" ? item.zh : item.en}</strong></a> : <span key={item.key} className="admin-nav-disabled" aria-disabled="true"><span aria-hidden="true">{item.icon}</span><strong>{locale === "zh-CN" ? item.zh : item.en}</strong><em>NEXT</em></span>)}
        </section>)}
      </nav>
      <a className="admin-sidebar-collapse" href="/">← {zh(locale, "返回前台", "Back to product")}</a>
    </aside>
  );
}

function OverviewPage({ config, policy, secrets, audit, locale, globalAuthEnabled }: { config: RuntimeConfigPayload; policy: RuntimePolicyPayload; secrets: RuntimeSecretStatus[]; audit: RuntimeAuditItem[]; locale: string; globalAuthEnabled: boolean }) {
  const enabledAuth = [settingBool(config, "auth.email.enabled"), settingBool(config, "auth.google.enabled"), settingBool(config, "auth.steam.enabled")].filter(Boolean).length;
  const enabledProviders = config.ai_providers.filter((item) => item.enabled).length;
  const decisionProviders = config.ai_providers.filter((item) => item.enabled && item.decisions_enabled).length;
  const operationalSecrets = secrets.filter((item) => item.operational).length;
  const aiEnabled = policyBool(policy, "ai.decisions.enabled");
  return <div className="admin-page-stack">
    <AdminPageHeading title={zh(locale, "控制台概览", "Control plane overview")} detail={zh(locale, "查看认证、AI 调度、运行时策略与加密凭据的实时状态。", "Inspect live authentication, AI scheduling, runtime policy and encrypted credential state.")} />
    <section className="admin-metric-grid">
      <MetricCard icon="▣" label={zh(locale, "认证方式", "Auth methods")} value={`${enabledAuth} / 3`} detail={zh(locale, "当前已启用", "enabled now")} tone="blue" />
      <MetricCard icon="⌘" label={zh(locale, "AI 提供商", "AI providers")} value={`${enabledProviders} / ${config.ai_providers.length}`} detail={aiEnabled ? zh(locale, "AI 调度已开启", "AI scheduling enabled") : zh(locale, "AI 调度已暂停", "AI scheduling paused")} tone="green" />
      <MetricCard icon="◉" label={zh(locale, "参与决策", "Decision fan-out")} value={String(decisionProviders)} detail={policy.ai_contract.fan_out_strategy} tone="purple" />
      <MetricCard icon="◇" label={zh(locale, "可用凭据", "Operational secrets")} value={`${operationalSecrets} / ${secrets.length}`} detail={config.bootstrap.encrypted_secret_storage_available ? "pgcrypto ready" : zh(locale, "缺少 Master Key", "Master key missing")} tone="orange" />
    </section>
    <section className="admin-overview-grid">
      <div className="admin-panel admin-panel-span-5"><div className="admin-panel-heading"><h2>{zh(locale, "认证方式状态", "Authentication status")}</h2><a href="/admin/runtime/auth">{zh(locale, "管理认证", "Manage")}</a></div><div className="admin-compact-list">
        <CompactStatus label={zh(locale, "全局认证", "Global auth")} enabled={globalAuthEnabled} />
        <CompactStatus label={zh(locale, "邮箱登录", "Email login")} enabled={settingBool(config, "auth.email.enabled")} />
        <CompactStatus label="Google OAuth" enabled={settingBool(config, "auth.google.enabled")} />
        <CompactStatus label="Steam OpenID" enabled={settingBool(config, "auth.steam.enabled")} />
      </div></div>
      <div className="admin-panel admin-panel-span-7"><div className="admin-panel-heading"><h2>{zh(locale, "AI 提供商状态", "AI provider status")}</h2><a href="/admin/runtime/ai-providers">{zh(locale, "管理提供商", "Manage")}</a></div><ProviderTable providers={config.ai_providers} locale={locale} compact /></div>
      <div className="admin-panel admin-panel-span-8"><div className="admin-panel-heading"><h2>{zh(locale, "最近配置变更", "Recent configuration changes")}</h2></div><AuditList audit={audit.slice(0, 6)} locale={locale} /></div>
      <div className="admin-panel admin-panel-span-4"><div className="admin-panel-heading"><h2>{zh(locale, "运行时语义", "Runtime semantics")}</h2></div><dl className="admin-system-list">
        <SystemRow label="Prompt" value={policy.ai_contract.prompt_version} />
        <SystemRow label="Decision Policy" value={policy.ai_contract.decision_policy_version} />
        <SystemRow label="AI View" value={policy.ai_contract.ai_view_version} />
        <SystemRow label={zh(locale, "Worker 并发", "Worker concurrency")} value={`${policy.ai_contract.worker_concurrency} · bootstrap`} />
        <SystemRow label={zh(locale, "PREPARE 冻结", "PREPARE freeze")} value={zh(locale, "已启用", "Enabled")} />
      </dl></div>
    </section>
  </div>;
}

function AuthenticationPage({ config, secrets, globalAuthEnabled, locale, busy, onSetting, onSecret }: { config: RuntimeConfigPayload; secrets: RuntimeSecretStatus[]; globalAuthEnabled: boolean; locale: string; busy: boolean; onSetting: (key: string, value: unknown) => Promise<void>; onSecret: (key: string, value: string) => Promise<void> }) {
  const baseUrl = settingString(config, "auth.external_base_url") || "http://127.0.0.1:5173";
  const googleSecret = secrets.find((item) => item.key === "auth.google.client_secret");
  return <div className="admin-page-stack">
    <AdminPageHeading title={zh(locale, "认证配置", "Authentication")} detail={zh(locale, "全局认证由启动参数控制；以下登录方式和 OAuth 配置支持运行时更新。", "Global authentication is controlled at startup; the login methods and OAuth settings below are hot-updatable.")} />
    <div className={`admin-security-banner ${globalAuthEnabled ? "" : "is-warning"}`}>
      {globalAuthEnabled
        ? zh(locale, "全局认证已启用。修改邮箱、Google 或 Steam 登录方式会立即影响后续请求。", "Global authentication is enabled. Changes to Email, Google or Steam providers affect subsequent requests immediately.")
        : zh(locale, "全局认证未启用。请设置 AUTH_ENABLED=true 并重启服务；下方登录方式开关不会单独启用全局认证。", "Global authentication is disabled. Set AUTH_ENABLED=true and restart the service; provider switches below cannot enable it by themselves.")}
    </div>
    <section className="admin-auth-stack">
      <AuthCard icon="✉" title={zh(locale, "邮箱登录", "Email login")} enabled={settingBool(config, "auth.email.enabled")} busy={busy} onToggle={(value) => onSetting("auth.email.enabled", value)}>
        <div className="admin-auth-detail-grid"><InfoCell label="OTP" value={zh(locale, "一次性验证码", "One-time code")} /><InfoCell label={zh(locale, "运行时行为", "Runtime behavior")} value={zh(locale, "关闭后立即拒绝 request/verify", "Immediately rejects request/verify when off")} /></div>
      </AuthCard>
      <AuthCard icon="G" title={zh(locale, "Google 登录", "Google login")} enabled={settingBool(config, "auth.google.enabled")} busy={busy} onToggle={(value) => onSetting("auth.google.enabled", value)}>
        <div className="admin-auth-detail-grid admin-auth-detail-grid-2">
          <InlineSettingEditor label="Client ID" value={settingString(config, "auth.google.client_id")} busy={busy} onSave={(value) => onSetting("auth.google.client_id", value)} />
          <InlineSettingEditor label="External Base URL" value={baseUrl} busy={busy} onSave={(value) => onSetting("auth.external_base_url", value)} />
          <InfoCell label="Callback URL" value={`${baseUrl.replace(/\/$/, "")}/api/auth/google/callback`} mono />
          <SecretInlineStatus label="Client Secret" secret={googleSecret} locale={locale} busy={busy} onReplace={(value) => onSecret("auth.google.client_secret", value)} />
        </div>
      </AuthCard>
      <AuthCard icon="S" title={zh(locale, "Steam 登录", "Steam login")} enabled={settingBool(config, "auth.steam.enabled")} busy={busy} onToggle={(value) => onSetting("auth.steam.enabled", value)}>
        <div className="admin-auth-detail-grid admin-auth-detail-grid-2"><InfoCell label="Callback URL" value={`${baseUrl.replace(/\/$/, "")}/api/auth/steam/callback`} mono /><InfoCell label="Realm" value={`${baseUrl.replace(/\/$/, "")}/`} mono /></div>
      </AuthCard>
    </section>
  </div>;
}

function AiProvidersPage({ config, secrets, locale, busy, onProvider, onSecret }: { config: RuntimeConfigPayload; secrets: RuntimeSecretStatus[]; locale: string; busy: boolean; onProvider: (provider: RuntimeAiProviderRecord, changes: Parameters<typeof updateRuntimeAiProvider>[2]) => Promise<void>; onSecret: (key: string, value: string) => Promise<void> }) {
  const [editing, setEditing] = React.useState<string | null>(null);
  return <div className="admin-page-stack">
    <AdminPageHeading title={zh(locale, "AI 提供商", "AI Providers")} detail={zh(locale, "控制 provider 总开关、是否参与决策、模型、Base URL、超时、思考强度与写入式 API Key。", "Control provider availability, decision participation, model, Base URL, timeout, reasoning effort and write-only API keys.")} />
    <section className="admin-panel"><div className="admin-panel-heading"><h2>{zh(locale, "提供商管理", "Provider management")}</h2><span className="admin-runtime-note">{zh(locale, "修改仅影响后续 PREPARE", "Changes affect subsequent PREPARE only")}</span></div>
      <div className="admin-table-wrap"><table className="admin-table admin-provider-table"><thead><tr><th>{zh(locale, "提供商", "Provider")}</th><th>{zh(locale, "总开关", "Enabled")}</th><th>{zh(locale, "参与决策", "Decision")}</th><th>{zh(locale, "当前模型", "Model")}</th><th>Base URL</th><th>{zh(locale, "超时", "Timeout")}</th><th>{zh(locale, "思考强度", "Reasoning")}</th><th>API Key</th><th /></tr></thead><tbody>
        {config.ai_providers.map((provider) => <React.Fragment key={`${provider.provider}:${provider.slot}`}><tr>
          <td><ProviderIdentity provider={provider} /></td>
          <td><ToggleSwitch checked={provider.enabled} disabled={busy} ariaLabel={`${provider.provider} enabled`} onChange={(value) => void onProvider(provider, { enabled: value })} /></td>
          <td><ToggleSwitch checked={provider.decisions_enabled} disabled={busy || !provider.enabled} ariaLabel={`${provider.provider} decisions`} onChange={(value) => void onProvider(provider, { decisions_enabled: value })} /></td>
          <td className="admin-mono">{provider.model}</td><td className="admin-url-cell">{provider.base_url}</td><td>{provider.timeout_seconds}s</td><td>{provider.reasoning_supported ? (provider.reasoning_effort || "—") : "N/A"}</td>
          <td><SecretStatusPill secret={providerSecretStatus(provider, secrets)} locale={locale} /></td>
          <td><button type="button" className="admin-link-button" onClick={() => setEditing(editing === providerKey(provider) ? null : providerKey(provider))}>{zh(locale, "编辑", "Edit")}</button></td>
        </tr>{editing === providerKey(provider) && <tr className="admin-provider-editor-row"><td colSpan={9}><ProviderEditor provider={provider} secretStatus={providerSecretStatus(provider, secrets)} busy={busy} locale={locale} onCancel={() => setEditing(null)} onSave={async (changes) => { await onProvider(provider, changes); setEditing(null); }} onSecret={onSecret} /></td></tr>}</React.Fragment>)}
      </tbody></table></div>
    </section>
  </div>;
}

function AiDecisionSettingsPage({ config, policy, locale, busy, onPolicy }: { config: RuntimeConfigPayload; policy: RuntimePolicyPayload; locale: string; busy: boolean; onPolicy: (key: string, value: unknown) => Promise<void> }) {
  const active = config.ai_providers.filter((item) => item.enabled && item.decisions_enabled);
  return <div className="admin-page-stack">
    <AdminPageHeading title={zh(locale, "AI 决策设置", "AI decision settings")} detail={zh(locale, "这些参数在每次 PREPARE 时从数据库读取并冻结；修改不会改变已经开始执行的推理。", "These parameters are loaded and frozen at PREPARE; edits never mutate inference already in progress.")} />
    <section className="admin-policy-grid">
      <PolicyToggleCard title={zh(locale, "AI 决策总开关", "AI decision master switch")} detail={zh(locale, "关闭后不再为新快照调度 AI provider jobs，已 PREPARE 的请求继续完成。", "Stops scheduling provider jobs for new snapshots; already prepared requests finish normally.")} checked={policyBool(policy, "ai.decisions.enabled")} disabled={busy} onChange={(value) => void onPolicy("ai.decisions.enabled", value)} />
      <PolicyNumberCard label={zh(locale, "Live 数据最大滞后", "Maximum live-data lag")} unit={zh(locale, "秒", "seconds")} value={policyNumber(policy, "ai.max_live_data_lag_seconds")} min={1} max={3600} step={1} disabled={busy} onSave={(value) => onPolicy("ai.max_live_data_lag_seconds", value)} />
      <PolicyNumberCard label={zh(locale, "Prior Context 深度", "Prior decision context")} unit={zh(locale, "条", "decisions")} value={policyNumber(policy, "ai.prior_decisions_limit")} min={1} max={100} step={1} integer disabled={busy} onSave={(value) => onPolicy("ai.prior_decisions_limit", value)} />
      <ReadOnlyPolicyCard title="Provider Fan-out" value={policy.ai_contract.fan_out_strategy} detail={`${active.length} ${zh(locale, "个当前参与决策", "active decision providers")}`} />
      <ReadOnlyPolicyCard title={zh(locale, "Worker 并发", "Worker concurrency")} value={String(policy.ai_contract.worker_concurrency)} detail={zh(locale, "进程生命周期参数；在 Dynamic Supervisor 完成前保持只读，避免伪热更新。", "Process-lifecycle setting; intentionally read-only until Dynamic Supervisor can resize safely.")} warning />
      <ReadOnlyPolicyCard title={zh(locale, "冻结身份", "Frozen contract")} value={policy.ai_contract.ai_view_version} detail={`${policy.ai_contract.prompt_version} · ${policy.ai_contract.decision_policy_version}`} />
    </section>
    <section className="admin-panel"><div className="admin-panel-heading"><h2>{zh(locale, "当前决策路由", "Current decision route")}</h2></div><ProviderTable providers={active} locale={locale} /></section>
  </div>;
}

function FeatureFlagsPage({ policy, locale, busy, onPolicy }: { policy: RuntimePolicyPayload; locale: string; busy: boolean; onPolicy: (key: string, value: unknown) => Promise<void> }) {
  return <div className="admin-page-stack">
    <AdminPageHeading title={zh(locale, "功能开关", "Feature flags")} detail={zh(locale, "只开放已经具有真实无重启语义的开关；长期 worker 类型不会伪装成热切。", "Only switches with real no-restart semantics are editable; long-running worker lifecycles are not presented as fake hot toggles.")} />
    <section className="admin-feature-grid">
      <FeatureCard icon="AI" title={zh(locale, "AI 决策", "AI decisions")} detail={zh(locale, "控制新快照的 AI 调度", "Controls AI scheduling for new snapshots")} checked={policyBool(policy, "ai.decisions.enabled")} disabled={busy} onChange={(value) => void onPolicy("ai.decisions.enabled", value)} />
      <FeatureCard icon="↗" title="Performance Dashboard" detail={zh(locale, "硬门控 /api/review/* 质量与表现 API", "Hard-gates /api/review/* quality and performance APIs")} checked={policyBool(policy, "feature.performance.enabled")} disabled={busy} onChange={(value) => void onPolicy("feature.performance.enabled", value)} />
      <FeatureCard icon="$" title={zh(locale, "Billing 新付费访问", "New paid-access checkout")} detail={zh(locale, "关闭新 checkout，保留账户查询与 Paddle webhook 对账", "Disables new checkout while account reads and Paddle webhooks remain active")} checked={policyBool(policy, "feature.billing_checkout.enabled")} disabled={busy} onChange={(value) => void onPolicy("feature.billing_checkout.enabled", value)} />
    </section>
    <section className="admin-panel"><div className="admin-panel-heading"><h2>{zh(locale, "生命周期型能力", "Lifecycle-managed capabilities")}</h2><span className="admin-runtime-note">Dynamic Supervisor NEXT</span></div><div className="admin-lifecycle-grid">{policy.lifecycle_features.map((feature) => <LifecycleFeatureCard key={feature.key} feature={feature} locale={locale} />)}</div></section>
  </div>;
}

function SecretsPage({ secrets, encryptedStorage, locale, busy, onSecret }: { secrets: RuntimeSecretStatus[]; encryptedStorage: boolean; locale: string; busy: boolean; onSecret: (key: string, value: string) => Promise<void> }) {
  const [selected, setSelected] = React.useState<string | null>(null);
  const selectedSecret = secrets.find((item) => item.key === selected) ?? null;
  return <div className="admin-page-stack">
    <AdminPageHeading title={zh(locale, "外部服务与密钥", "External services & secrets")} detail={zh(locale, "密钥只支持写入与替换，读取 API 永不返回明文。Google OAuth 与 AI provider 会在后续请求中直接使用最新密钥。", "Secrets are write/replace only; read APIs never return plaintext. Google OAuth and AI providers use the latest secret on subsequent requests.")} />
    {!encryptedStorage && <div className="admin-security-banner is-warning">⚠ {zh(locale, "当前缺少 DOTA_RUNTIME_CONFIG_MASTER_KEY，无法安全写入数据库密钥。", "DOTA_RUNTIME_CONFIG_MASTER_KEY is missing; encrypted database secret writes are unavailable.")}</div>}
    <div className="admin-security-banner">ⓘ {zh(locale, "数据库密钥使用 PostgreSQL pgcrypto 加密；审计日志只记录 REPLACED，不记录密钥值。", "Database secrets use PostgreSQL pgcrypto; audit rows record REPLACED without secret values.")}</div>
    <section className="admin-panel"><div className="admin-panel-heading"><h2>{zh(locale, "受管凭据", "Managed credentials")}</h2><span className="admin-runtime-note">{secrets.filter((item) => item.operational).length} / {secrets.length} {zh(locale, "运行可用", "operational")}</span></div>
      <div className="admin-table-wrap"><table className="admin-table admin-secret-table"><thead><tr><th>{zh(locale, "凭据", "Credential")}</th><th>{zh(locale, "类别", "Category")}</th><th>{zh(locale, "状态", "Status")}</th><th>{zh(locale, "存储来源", "Storage")}</th><th>{zh(locale, "运行时生效", "Runtime")}</th><th /></tr></thead><tbody>{secrets.map((secret) => <tr key={secret.key}><td><strong>{secret.label}</strong><small className="admin-secret-key">{secret.key}</small></td><td>{secret.category}</td><td><SecretStatusPill secret={secret} locale={locale} /></td><td><StorageBadge storage={secret.storage} locale={locale} /></td><td>{secret.runtime_hot ? zh(locale, "后续请求", "Next request") : "—"}</td><td><button type="button" className="admin-link-button" onClick={() => setSelected(secret.key)}>{secret.configured ? zh(locale, "替换", "Replace") : zh(locale, "配置", "Configure")}</button></td></tr>)}</tbody></table></div>
    </section>
    {selectedSecret && <SecretReplacePanel secret={selectedSecret} locale={locale} busy={busy || !encryptedStorage} onCancel={() => setSelected(null)} onSave={async (value) => { await onSecret(selectedSecret.key, value); setSelected(null); }} />}
  </div>;
}

function ProviderEditor({ provider, secretStatus, busy, locale, onCancel, onSave, onSecret }: { provider: RuntimeAiProviderRecord; secretStatus: RuntimeSecretStatus | undefined; busy: boolean; locale: string; onCancel: () => void; onSave: (changes: Parameters<typeof updateRuntimeAiProvider>[2]) => Promise<void>; onSecret: (key: string, value: string) => Promise<void> }) {
  const [model, setModel] = React.useState(provider.model);
  const [baseUrl, setBaseUrl] = React.useState(provider.base_url);
  const [timeout, setTimeout] = React.useState(String(provider.timeout_seconds));
  const [reasoning, setReasoning] = React.useState(provider.reasoning_effort || "medium");
  const [secret, setSecret] = React.useState("");
  const save = async () => {
    const changes: Parameters<typeof updateRuntimeAiProvider>[2] = { model: model.trim(), base_url: baseUrl.trim(), timeout_seconds: Number(timeout) };
    if (provider.reasoning_supported) changes.reasoning_effort = reasoning;
    await onSave(changes);
  };
  return <div className="admin-provider-editor"><div className="admin-editor-fields"><label>Model<input aria-label="Model" value={model} onChange={(event) => setModel(event.target.value)} /></label><label>Base URL<input aria-label="Base URL" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label><label>{zh(locale, "超时（秒）", "Timeout seconds")}<input aria-label="Timeout seconds" type="number" min="1" max="300" value={timeout} onChange={(event) => setTimeout(event.target.value)} /></label>{provider.reasoning_supported && <label>{zh(locale, "思考强度", "Reasoning effort")}<select aria-label="Reasoning effort" value={reasoning} onChange={(event) => setReasoning(event.target.value)}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></label>}</div>
    <div className="admin-secret-edit-row"><div><strong>API Key</strong><small><SecretStatusPill secret={secretStatus} locale={locale} /> </small></div><input type="password" aria-label={`${provider.provider} API key`} placeholder={zh(locale, "输入新 Key，仅用于替换", "Enter a new key to replace")} value={secret} onChange={(event) => setSecret(event.target.value)} /><button type="button" className="admin-secondary-button" disabled={busy || !secret || !provider.api_key_secret_key} onClick={() => { if (!provider.api_key_secret_key || !secret) return; const value = secret; setSecret(""); void onSecret(provider.api_key_secret_key, value); }}>{zh(locale, "替换 Key", "Replace key")}</button></div>
    <div className="admin-editor-actions"><button type="button" className="admin-secondary-button" onClick={onCancel}>{zh(locale, "取消", "Cancel")}</button><button type="button" className="admin-primary-button" disabled={busy || !model.trim() || !baseUrl.trim() || !Number(timeout)} onClick={() => void save()}>{zh(locale, "保存提供商配置", "Save provider configuration")}</button></div></div>;
}

function AuthCard({ icon, title, enabled, busy, onToggle, children }: { icon: string; title: string; enabled: boolean; busy: boolean; onToggle: (value: boolean) => void; children: React.ReactNode }) {
  return <section className="admin-auth-card"><div className="admin-auth-card-head"><span className="admin-auth-icon">{icon}</span><div><strong>{title}</strong><StatusPill enabled={enabled} enabledText="已启用" disabledText="已禁用" /></div><ToggleSwitch checked={enabled} disabled={busy} ariaLabel={`${title} enabled`} onChange={onToggle} /></div><div className="admin-auth-card-body">{children}</div></section>;
}

function InlineSettingEditor({ label, value, busy, onSave }: { label: string; value: string; busy: boolean; onSave: (value: string) => Promise<void> }) {
  const [draft, setDraft] = React.useState(value);
  React.useEffect(() => setDraft(value), [value]);
  return <label className="admin-inline-setting"><span>{label}</span><div><input value={draft} onChange={(event) => setDraft(event.target.value)} /><button type="button" className="admin-link-button" disabled={busy || !draft.trim() || draft === value} onClick={() => void onSave(draft.trim())}>保存</button></div></label>;
}

function SecretInlineStatus({ label, secret, locale, busy, onReplace }: { label: string; secret: RuntimeSecretStatus | undefined; locale: string; busy: boolean; onReplace: (value: string) => Promise<void> }) {
  const [draft, setDraft] = React.useState("");
  return <div className="admin-inline-secret"><span>{label}</span><div><SecretStatusPill secret={secret} locale={locale} /><input type="password" aria-label={label} placeholder="••••••••" value={draft} onChange={(event) => setDraft(event.target.value)} /><button type="button" className="admin-secondary-button" disabled={busy || !draft} onClick={async () => { await onReplace(draft); setDraft(""); }}>替换</button></div></div>;
}

function PolicyToggleCard({ title, detail, checked, disabled, onChange }: { title: string; detail: string; checked: boolean; disabled: boolean; onChange: (value: boolean) => void }) {
  return <section className="admin-policy-card"><div className="admin-policy-card-head"><div><strong>{title}</strong><p>{detail}</p></div><ToggleSwitch checked={checked} disabled={disabled} ariaLabel={`${title} enabled`} onChange={onChange} /></div><StatusPill enabled={checked} enabledText="ACTIVE" disabledText="PAUSED" /></section>;
}

function PolicyNumberCard({ label, unit, value, min, max, step, integer, disabled, onSave }: { label: string; unit: string; value: number; min: number; max: number; step: number; integer?: boolean; disabled: boolean; onSave: (value: number) => Promise<void> }) {
  const [draft, setDraft] = React.useState(String(value));
  React.useEffect(() => setDraft(String(value)), [value]);
  const parsed = integer ? Number.parseInt(draft, 10) : Number(draft);
  const valid = Number.isFinite(parsed) && parsed >= min && parsed <= max;
  return <section className="admin-policy-card"><strong>{label}</strong><div className="admin-number-control"><input aria-label={label} type="number" min={min} max={max} step={step} value={draft} onChange={(event) => setDraft(event.target.value)} /><span>{unit}</span></div><button type="button" className="admin-secondary-button" disabled={disabled || !valid || parsed === value} onClick={() => void onSave(parsed)}>保存</button></section>;
}

function ReadOnlyPolicyCard({ title, value, detail, warning }: { title: string; value: string; detail: string; warning?: boolean }) {
  return <section className={`admin-policy-card ${warning ? "is-warning" : ""}`}><strong>{title}</strong><b className="admin-policy-value">{value}</b><p>{detail}</p>{warning && <span className="admin-readonly-badge">READ ONLY</span>}</section>;
}

function FeatureCard({ icon, title, detail, checked, disabled, onChange }: { icon: string; title: string; detail: string; checked: boolean; disabled: boolean; onChange: (value: boolean) => void }) {
  return <section className="admin-feature-card"><span className="admin-feature-icon">{icon}</span><div><strong>{title}</strong><p>{detail}</p><StatusPill enabled={checked} enabledText="已启用" disabledText="已禁用" /></div><ToggleSwitch checked={checked} disabled={disabled} ariaLabel={`${title} feature`} onChange={onChange} /></section>;
}

function LifecycleFeatureCard({ feature, locale }: { feature: RuntimeLifecycleFeature; locale: string }) {
  return <article className="admin-lifecycle-card"><div><strong>{feature.label}</strong><StatusPill enabled={feature.enabled} enabledText={zh(locale, "进程已启用", "Process enabled")} disabledText={zh(locale, "进程未启用", "Process disabled")} /></div><p>{zh(locale, "当前由进程生命周期管理；待 Dynamic Supervisor 支持安全 add/remove worker 后再开放热开关。", feature.reason)}</p><span className="admin-readonly-badge">LIFECYCLE</span></article>;
}

function SecretReplacePanel({ secret, locale, busy, onCancel, onSave }: { secret: RuntimeSecretStatus; locale: string; busy: boolean; onCancel: () => void; onSave: (value: string) => Promise<void> }) {
  const [value, setValue] = React.useState("");
  return <section className="admin-secret-replace-panel"><div><strong>{secret.label}</strong><small>{secret.key}</small><p>{zh(locale, "输入新值后会直接替换；旧值和新值都不会出现在读取 API 或审计内容中。", "The new value replaces the old one; neither is returned by read APIs or audit content.")}</p></div><input type="password" aria-label={`${secret.label} new value`} autoComplete="new-password" value={value} onChange={(event) => setValue(event.target.value)} placeholder={zh(locale, "输入新密钥", "Enter new secret")} /><div><button type="button" className="admin-secondary-button" onClick={onCancel}>{zh(locale, "取消", "Cancel")}</button><button type="button" className="admin-primary-button" disabled={busy || !value} onClick={() => void onSave(value)}>{zh(locale, "加密保存并替换", "Encrypt and replace")}</button></div></section>;
}

function ProviderTable({ providers, locale, compact }: { providers: RuntimeAiProviderRecord[]; locale: string; compact?: boolean }) {
  return <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>{zh(locale, "提供商", "Provider")}</th><th>{zh(locale, "状态", "Status")}</th><th>{zh(locale, "模型", "Model")}</th><th>{zh(locale, "参与决策", "Decision")}</th>{!compact && <th>{zh(locale, "超时", "Timeout")}</th>}</tr></thead><tbody>{providers.map((provider) => <tr key={providerKey(provider)}><td><ProviderIdentity provider={provider} /></td><td><StatusPill enabled={provider.enabled} enabledText={zh(locale, "启用", "Enabled")} disabledText={zh(locale, "禁用", "Disabled")} /></td><td className="admin-mono">{provider.model}</td><td>{provider.decisions_enabled ? "✓" : "—"}</td>{!compact && <td>{provider.timeout_seconds}s</td>}</tr>)}</tbody></table></div>;
}

function ProviderIdentity({ provider }: { provider: RuntimeAiProviderRecord }) {
  const symbols: Record<string, string> = { openai: "O", local_openai: "L", anthropic: "A", gemini: "G", deepseek: "D", kimi: "K" };
  return <div className={`admin-provider-identity provider-${provider.provider}`}><span>{symbols[provider.provider] || provider.provider.slice(0, 1).toUpperCase()}</span><div><strong>{providerName(provider)}</strong><small>{provider.slot}</small></div></div>;
}

function CompactStatus({ label, enabled }: { label: string; enabled: boolean }) {
  return <div className="admin-compact-row"><strong>{label}</strong><StatusPill enabled={enabled} enabledText="Enabled" disabledText="Disabled" /></div>;
}

function AuditList({ audit, locale }: { audit: RuntimeAuditItem[]; locale: string }) {
  if (!audit.length) return <div className="admin-empty-panel">{zh(locale, "暂无配置变更", "No configuration changes yet")}</div>;
  return <div className="admin-audit-list">{audit.map((item) => <div key={item.id}><span className="admin-audit-dot" /><div><strong>{auditTitle(item, locale)}</strong><small>{item.actor || "system"} · {formatDateTime(item.created_at)}</small></div><em>{item.secret_changed ? "SECRET" : item.category}</em></div>)}</div>;
}

function InfoCell({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div className="admin-info-cell"><span>{label}</span><strong className={mono ? "admin-mono" : undefined}>{value}</strong></div>;
}

function SystemRow({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function MetricCard({ icon, label, value, detail, tone }: { icon: string; label: string; value: string; detail: string; tone: "blue" | "green" | "purple" | "orange" }) {
  return <article className={`admin-metric-card tone-${tone}`}><span className="admin-metric-icon">{icon}</span><div><small>{label}</small><strong>{value}</strong><span>{detail}</span></div><i aria-hidden="true" /></article>;
}

function AdminPageHeading({ title, detail }: { title: string; detail: string }) {
  return <header className="admin-page-heading"><h1>{title}</h1><p>{detail}</p></header>;
}

function ToggleSwitch({ checked, disabled, ariaLabel, onChange }: { checked: boolean; disabled?: boolean; ariaLabel: string; onChange: (value: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={ariaLabel} className={`admin-toggle ${checked ? "is-on" : ""}`} disabled={disabled} onClick={() => onChange(!checked)}><span /></button>;
}

function StatusPill({ enabled, enabledText, disabledText }: { enabled: boolean; enabledText: string; disabledText: string }) {
  return <span className={`admin-status-pill ${enabled ? "is-enabled" : "is-disabled"}`}>{enabled ? enabledText : disabledText}</span>;
}

function SecretStatusPill({ secret, locale }: { secret: RuntimeSecretStatus | undefined; locale: string }) {
  const operational = Boolean(secret?.operational);
  const configured = Boolean(secret?.configured);
  return <StatusPill
    enabled={operational}
    enabledText={zh(locale, "运行可用", "Operational")}
    disabledText={configured ? zh(locale, "不可用", "Unavailable") : zh(locale, "未配置", "Missing")}
  />;
}

function StorageBadge({ storage, locale }: { storage: string; locale: string }) {
  if (storage === "DATABASE_ENCRYPTED") return <span className="admin-storage-badge is-db">{zh(locale, "数据库加密", "Encrypted DB")}</span>;
  if (storage === "BOOTSTRAP_FALLBACK") return <span className="admin-storage-badge is-bootstrap">{zh(locale, "Bootstrap fallback", "Bootstrap fallback")}</span>;
  return <span className="admin-storage-badge is-none">—</span>;
}

function AdminRuntimeLoading() {
  return <div className="admin-loading-state"><span className="admin-loading-mark">D</span><strong>Loading Runtime Control Plane…</strong></div>;
}

function AdminRuntimeAccessState({ title, detail, actionLabel, onAction }: { title: string; detail: string; actionLabel?: string; onAction?: () => void }) {
  return <div className="admin-access-state"><span className="admin-loading-mark">D</span><h1>{title}</h1><p>{detail}</p>{actionLabel && onAction && <button type="button" className="admin-primary-button" onClick={onAction}>{actionLabel}</button>}</div>;
}

function sectionFromPath(pathname: string): AdminRuntimeSection {
  if (pathname.startsWith("/admin/runtime/auth")) return "auth";
  if (pathname.startsWith("/admin/runtime/ai-providers")) return "ai-providers";
  if (pathname.startsWith("/admin/runtime/ai-decisions")) return "ai-decisions";
  if (pathname.startsWith("/admin/runtime/features")) return "features";
  if (pathname.startsWith("/admin/runtime/secrets")) return "secrets";
  return "overview";
}

function setting(config: RuntimeConfigPayload, key: string): RuntimeSettingRecord | undefined { return config.settings.find((item) => item.key === key); }
function settingBool(config: RuntimeConfigPayload, key: string): boolean { return Boolean(setting(config, key)?.value); }
function settingString(config: RuntimeConfigPayload, key: string): string { const value = setting(config, key)?.value; return typeof value === "string" ? value : ""; }
function policySetting(policy: RuntimePolicyPayload, key: string): RuntimeSettingRecord | undefined { return policy.settings.find((item) => item.key === key); }
function policyBool(policy: RuntimePolicyPayload, key: string): boolean { return Boolean(policySetting(policy, key)?.value); }
function policyNumber(policy: RuntimePolicyPayload, key: string): number { const value = policySetting(policy, key)?.value; return typeof value === "number" ? value : Number(value ?? 0); }
function providerKey(provider: RuntimeAiProviderRecord): string { return `${provider.provider}:${provider.slot}`; }
function providerSecretStatus(provider: RuntimeAiProviderRecord, secrets: RuntimeSecretStatus[]): RuntimeSecretStatus | undefined { return secrets.find((item) => item.key === provider.api_key_secret_key); }
function providerName(provider: RuntimeAiProviderRecord): string { if (provider.provider === "local_openai") return "Local OpenAI"; if (provider.provider === "deepseek") return provider.slot === "pro" ? "DeepSeek Pro" : "DeepSeek Flash"; return provider.provider.charAt(0).toUpperCase() + provider.provider.slice(1); }
function latestUpdate(config: RuntimeConfigPayload, policy: RuntimePolicyPayload): string | null { const values = [...config.settings.map((item) => item.updated_at), ...config.ai_providers.map((item) => item.updated_at), ...policy.settings.map((item) => item.updated_at)].filter(Boolean).sort(); return values.at(-1) ?? null; }
function formatDateTime(value: string | null | undefined): string { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date); }
function errorText(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function auditTitle(item: RuntimeAuditItem, locale: string): string { if (item.secret_changed) return `${item.target_key} · ${zh(locale, "密钥已替换", "secret replaced")}`; return `${item.target_key} · ${item.operation}`; }
function zh(locale: string, chinese: string, english: string): string { return locale === "zh-CN" ? chinese : english; }
