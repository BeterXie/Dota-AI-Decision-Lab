import { expect, test, type Page, type Route } from "playwright/test";

const now = "2026-08-18T12:42:12Z";

interface RuntimeHarness {
  patches: Array<{ path: string; body: unknown }>;
  mapRequests: () => number;
}

async function mockRuntimeAdmin(page: Page): Promise<RuntimeHarness> {
  const patches: Array<{ path: string; body: unknown }> = [];
  let mapRequests = 0;
  let steamEnabled = true;
  let openAiModel = "gpt-5.6-terra";
  let aiDecisionsEnabled = true;
  let performanceEnabled = true;
  let billingCheckoutEnabled = true;
  let maxLiveLag = 120;
  let priorLimit = 10;
  const configuredSecrets = new Set([
    "auth.google.client_secret",
    "ai.openai.api_key",
    "ai.anthropic.api_key",
    "ai.deepseek.api_key",
    "ai.kimi.api_key"
  ]);

  const settings = () => [
    setting("auth.email.enabled", true, "auth"),
    setting("auth.google.enabled", false, "auth"),
    setting("auth.google.client_id", "client.apps.googleusercontent.com", "auth"),
    setting("auth.steam.enabled", steamEnabled, "auth"),
    setting("auth.external_base_url", "http://127.0.0.1:5173", "auth")
  ];

  const policySettings = () => [
    setting("ai.decisions.enabled", aiDecisionsEnabled, "ai_decision"),
    setting("ai.max_live_data_lag_seconds", maxLiveLag, "ai_decision"),
    setting("ai.prior_decisions_limit", priorLimit, "ai_decision"),
    setting("feature.performance.enabled", performanceEnabled, "feature"),
    setting("feature.billing_checkout.enabled", billingCheckoutEnabled, "feature")
  ];

  const providers = () => [
    provider("openai", "default", openAiModel, true, true, true, "high", 30),
    provider("anthropic", "default", "claude-sonnet-4-6", true, false, true, null, 30),
    provider(
      "gemini",
      "default",
      "gemini-3.6-flash",
      true,
      false,
      configuredSecrets.has("ai.gemini.api_key"),
      null,
      30
    ),
    provider("deepseek", "flash", "deepseek-v4-flash", true, false, true, "medium", 30),
    provider("deepseek", "pro", "deepseek-v4-pro", true, true, true, "medium", 30),
    provider("kimi", "default", "kimi-k2.5", false, false, true, null, 45)
  ];

  const secretItems = () => [
    secretStatus(
      "auth.google.client_secret",
      "Google Client Secret",
      "authentication",
      configuredSecrets
    ),
    secretStatus("ai.openai.api_key", "OpenAI API Key", "ai", configuredSecrets),
    secretStatus(
      "ai.local_openai.api_key",
      "Local OpenAI-compatible API Key",
      "ai",
      configuredSecrets
    ),
    secretStatus("ai.anthropic.api_key", "Anthropic API Key", "ai", configuredSecrets),
    secretStatus("ai.gemini.api_key", "Gemini API Key", "ai", configuredSecrets),
    secretStatus("ai.deepseek.api_key", "DeepSeek API Key", "ai", configuredSecrets),
    secretStatus("ai.kimi.api_key", "Kimi API Key", "ai", configuredSecrets)
  ];

  await page.addInitScript(() =>
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN")
  );
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === "/api/auth/session") {
      await json(route, {
        enabled: true,
        authenticated: true,
        user: {
          id: "99999999-9999-9999-9999-999999999999",
          email: "dev@localhost",
          email_verified_at: now,
          display_name: "BeterXie",
          avatar_url: null,
          created_at: "2026-08-01T10:00:00Z"
        },
        entitlements: ["ai_decisions", "realtime_notifications"],
        grants: [],
        providers: { email: true, google: false, steam: steamEnabled }
      });
      return;
    }

    if (path === "/api/admin/runtime/config" && request.method() === "GET") {
      await json(route, {
        settings: settings(),
        ai_providers: providers(),
        bootstrap: { encrypted_secret_storage_available: true, admin_email_count: 1 }
      });
      return;
    }

    if (path === "/api/admin/runtime/policy" && request.method() === "GET") {
      await json(route, {
        settings: policySettings(),
        ai_contract: {
          prompt_version: "decision-analyst-v5.1-output",
          decision_policy_version: "shadow-tournament-portfolio-v3",
          ai_view_version: "ai-view-v6",
          fan_out_strategy: "PARALLEL_ACTIVE_PROVIDERS",
          worker_concurrency: 4,
          worker_concurrency_hot_mutable: false
        },
        lifecycle_features: [
          lifecycle("email_notifications", "Email notifications", false),
          lifecycle("qq_bot", "QQ Bot", false),
          lifecycle("wechat_clawbot", "WeChat ClawBot", false),
          lifecycle("raybet_workers", "RayBet collectors", true),
          lifecycle("dltv_workers", "DLTV collectors", true)
        ]
      });
      return;
    }

    if (path === "/api/admin/runtime/secrets" && request.method() === "GET") {
      await json(route, { items: secretItems() });
      return;
    }

    if (path === "/api/admin/runtime/audit") {
      await json(route, {
        items: [
          {
            id: "audit-1",
            target_key: "auth.steam.enabled",
            category: "auth",
            operation: "UPDATE",
            previous_value: false,
            new_value: true,
            secret_changed: false,
            actor: "dev@localhost",
            created_at: now
          },
          {
            id: "audit-2",
            target_key: "ai_provider:openai:default",
            category: "ai_provider",
            operation: "UPDATE",
            previous_value: null,
            new_value: null,
            secret_changed: false,
            actor: "dev@localhost",
            created_at: "2026-08-18T12:30:00Z"
          }
        ]
      });
      return;
    }

    if (
      path === "/api/admin/runtime/settings/auth.steam.enabled" &&
      request.method() === "PATCH"
    ) {
      const body = request.postDataJSON() as { value: boolean };
      patches.push({ path, body });
      steamEnabled = body.value;
      await json(route, setting("auth.steam.enabled", steamEnabled, "auth"));
      return;
    }

    if (path.startsWith("/api/admin/runtime/policy/") && request.method() === "PATCH") {
      const key = decodeURIComponent(path.slice("/api/admin/runtime/policy/".length));
      const body = request.postDataJSON() as { value: unknown };
      patches.push({ path, body });
      if (key === "ai.decisions.enabled") aiDecisionsEnabled = Boolean(body.value);
      if (key === "ai.max_live_data_lag_seconds") maxLiveLag = Number(body.value);
      if (key === "ai.prior_decisions_limit") priorLimit = Number(body.value);
      if (key === "feature.performance.enabled") performanceEnabled = Boolean(body.value);
      if (key === "feature.billing_checkout.enabled") billingCheckoutEnabled = Boolean(body.value);
      await json(
        route,
        setting(key, body.value, key.startsWith("feature.") ? "feature" : "ai_decision")
      );
      return;
    }

    if (
      path === "/api/admin/runtime/ai-providers/openai/default" &&
      request.method() === "PATCH"
    ) {
      const body = request.postDataJSON() as { model?: string };
      patches.push({ path, body });
      if (body.model) openAiModel = body.model;
      await json(
        route,
        provider("openai", "default", openAiModel, true, true, true, "high", 30)
      );
      return;
    }

    if (path.startsWith("/api/admin/runtime/secrets/") && request.method() === "PUT") {
      const key = decodeURIComponent(path.slice("/api/admin/runtime/secrets/".length));
      patches.push({ path, body: request.postDataJSON() });
      configuredSecrets.add(key);
      await json(route, { key, configured: true });
      return;
    }

    if (path === "/api/maps") mapRequests += 1;
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  return { patches, mapRequests: () => mapRequests };
}

test("runtime overview uses the full admin shell without loading match directory data", async ({
  page
}) => {
  const harness = await mockRuntimeAdmin(page);
  await page.goto("/admin/runtime");

  await expect(page.getByRole("heading", { name: "控制台概览" })).toBeVisible();
  await expect(page.getByText("认证方式状态", { exact: true })).toBeVisible();
  await expect(page.getByText("AI 提供商状态", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /认证配置/ })).toHaveAttribute(
    "href",
    "/admin/runtime/auth"
  );
  await expect(page.getByRole("link", { name: /AI 提供商/ })).toHaveAttribute(
    "href",
    "/admin/runtime/ai-providers"
  );
  await expect(page.getByRole("link", { name: /AI 决策设置/ })).toHaveAttribute(
    "href",
    "/admin/runtime/ai-decisions"
  );
  await expect(page.getByRole("link", { name: /功能开关/ })).toHaveAttribute(
    "href",
    "/admin/runtime/features"
  );
  await expect(page.getByRole("link", { name: /外部服务 \/ Secrets/ })).toHaveAttribute(
    "href",
    "/admin/runtime/secrets"
  );
  expect(harness.mapRequests()).toBe(0);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("authentication page hot-switches Steam through the runtime settings API", async ({
  page
}) => {
  const harness = await mockRuntimeAdmin(page);
  await page.goto("/admin/runtime/auth");

  await expect(page.getByRole("heading", { name: "认证配置" })).toBeVisible();
  await expect(page.getByText("Google 登录", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Steam 登录", { exact: true }).first()).toBeVisible();
  await page.getByRole("switch", { name: "Steam 登录 enabled" }).click();

  await expect.poll(() => harness.patches.length).toBe(1);
  expect(harness.patches[0]).toEqual({
    path: "/api/admin/runtime/settings/auth.steam.enabled",
    body: { value: false }
  });
  await expect(page.getByText(/配置已更新，后续请求立即使用新设置/)).toBeVisible();
});

test("AI providers page edits the model and keeps provider controls visible", async ({
  page
}) => {
  const harness = await mockRuntimeAdmin(page);
  await page.goto("/admin/runtime/ai-providers");

  await expect(page.getByRole("heading", { name: "AI 提供商" })).toBeVisible();
  await expect(page.getByText("gpt-5.6-terra", { exact: true })).toBeVisible();
  await expect(page.getByRole("switch", { name: "openai enabled" })).toBeVisible();
  await expect(page.getByRole("switch", { name: "openai decisions" })).toBeVisible();

  await page.getByRole("button", { name: "编辑" }).first().click();
  const editor = page.locator(".admin-provider-editor").first();
  await editor.getByLabel("Model").fill("gpt-5.6-terra-admin-test");
  await editor.getByRole("button", { name: "保存提供商配置" }).click();

  await expect
    .poll(() => harness.patches.some((entry) => entry.path.includes("/ai-providers/openai/default")))
    .toBe(true);
  const update = harness.patches.find(
    (entry) => entry.path === "/api/admin/runtime/ai-providers/openai/default"
  );
  expect(update?.body).toMatchObject({ model: "gpt-5.6-terra-admin-test" });
  await expect(page.getByText(/AI 提供商配置已更新，仅影响后续推理请求/)).toBeVisible();
});

test("AI decision settings hot-update the PREPARE policy and keep worker concurrency honest", async ({
  page
}) => {
  const harness = await mockRuntimeAdmin(page);
  await page.goto("/admin/runtime/ai-decisions");

  await expect(page.getByRole("heading", { name: "AI 决策设置" })).toBeVisible();
  await expect(page.getByText("Worker 并发", { exact: true })).toBeVisible();
  await expect(page.getByText("READ ONLY", { exact: true })).toBeVisible();
  const lag = page.getByLabel("Live 数据最大滞后");
  await lag.fill("90");
  await lag
    .locator("xpath=ancestor::section[1]")
    .getByRole("button", { name: "保存" })
    .click();

  await expect
    .poll(() =>
      harness.patches.some((entry) => entry.path.endsWith("/ai.max_live_data_lag_seconds"))
    )
    .toBe(true);
  expect(
    harness.patches.find((entry) => entry.path.endsWith("/ai.max_live_data_lag_seconds"))?.body
  ).toEqual({ value: 90 });
  await expect(page.getByText(/运行时策略已更新；正在执行中的请求保持冻结配置/)).toBeVisible();
});

test("feature flags expose only real hot switches and PATCH performance gate", async ({
  page
}) => {
  const harness = await mockRuntimeAdmin(page);
  await page.goto("/admin/runtime/features");

  await expect(page.getByRole("heading", { name: "功能开关" })).toBeVisible();
  await expect(page.getByText("生命周期型能力", { exact: true })).toBeVisible();
  await expect(page.getByText("QQ Bot", { exact: true })).toBeVisible();
  await page.getByRole("switch", { name: "Performance Dashboard feature" }).click();

  await expect
    .poll(() =>
      harness.patches.some((entry) => entry.path.endsWith("/feature.performance.enabled"))
    )
    .toBe(true);
  expect(
    harness.patches.find((entry) => entry.path.endsWith("/feature.performance.enabled"))?.body
  ).toEqual({ value: false });
});

test("secrets page replaces a missing key without ever rendering plaintext", async ({ page }) => {
  const harness = await mockRuntimeAdmin(page);
  const plaintext = "gemini-super-secret-runtime-value";
  await page.goto("/admin/runtime/secrets");

  await expect(page.getByRole("heading", { name: "外部服务与密钥" })).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: "Gemini API Key" });
  await expect(row.getByText("未配置", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "配置" }).click();
  await page.getByLabel("Gemini API Key new value").fill(plaintext);
  await page.getByRole("button", { name: "加密保存并替换" }).click();

  await expect
    .poll(() => harness.patches.some((entry) => entry.path.endsWith("/ai.gemini.api_key")))
    .toBe(true);
  expect(harness.patches.find((entry) => entry.path.endsWith("/ai.gemini.api_key"))?.body).toEqual({
    value: plaintext
  });
  await expect(page.getByText(plaintext, { exact: true })).toHaveCount(0);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "Gemini API Key" })
      .getByText("运行可用", { exact: true })
  ).toBeVisible();
});

function setting(key: string, value: unknown, category: string) {
  return {
    key,
    value,
    value_type:
      typeof value === "boolean" ? "BOOLEAN" : typeof value === "number" ? "NUMBER" : "STRING",
    category,
    description: null,
    revision: 2,
    updated_by: "dev@localhost",
    updated_at: now
  };
}

function provider(
  name: string,
  slot: string,
  model: string,
  enabled: boolean,
  decisionsEnabled: boolean,
  secretConfigured: boolean,
  reasoning: string | null,
  timeout: number
) {
  return {
    provider: name,
    slot,
    enabled,
    decisions_enabled: decisionsEnabled,
    base_url: name === "openai" ? "https://api.openai.com/v1" : `https://api.${name}.example/v1`,
    model,
    reasoning_effort: reasoning,
    reasoning_supported: ["openai", "local_openai", "deepseek"].includes(name),
    timeout_seconds: timeout,
    api_key_secret_key: `ai.${name}.api_key`,
    secret_configured: secretConfigured,
    revision: 3,
    updated_by: "dev@localhost",
    updated_at: now
  };
}

function secretStatus(key: string, label: string, category: string, configured: Set<string>) {
  const isConfigured = configured.has(key);
  return {
    key,
    label,
    category,
    configured: isConfigured,
    storage: isConfigured ? "DATABASE_ENCRYPTED" : "NOT_CONFIGURED",
    decryptable: isConfigured,
    operational: isConfigured,
    fallback_available: false,
    runtime_hot: true
  };
}

function lifecycle(key: string, label: string, enabled: boolean) {
  return {
    key,
    label,
    enabled,
    hot_mutable: false,
    reason: "Requires dynamic supervisor lifecycle management before no-restart toggling is safe."
  };
}

async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}
