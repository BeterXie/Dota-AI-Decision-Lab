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

  const settings = () => [
    setting("auth.email.enabled", true),
    setting("auth.google.enabled", false),
    setting("auth.google.client_id", "client.apps.googleusercontent.com"),
    setting("auth.steam.enabled", steamEnabled),
    setting("auth.external_base_url", "http://127.0.0.1:5173")
  ];

  const providers = () => [
    provider("openai", "default", openAiModel, true, true, true, "high", 30),
    provider("anthropic", "default", "claude-sonnet-4-6", true, false, false, null, 30),
    provider("gemini", "default", "gemini-3.6-flash", true, false, true, null, 30),
    provider("deepseek", "flash", "deepseek-v4-pro", true, true, true, "medium", 30),
    provider("kimi", "default", "kimi-k2", false, false, true, null, 45)
  ];

  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
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

    if (path === "/api/admin/runtime/settings/auth.steam.enabled" && request.method() === "PATCH") {
      const body = request.postDataJSON() as { value: boolean };
      patches.push({ path, body });
      steamEnabled = body.value;
      await json(route, setting("auth.steam.enabled", steamEnabled));
      return;
    }

    if (path === "/api/admin/runtime/ai-providers/openai/default" && request.method() === "PATCH") {
      const body = request.postDataJSON() as { model?: string };
      patches.push({ path, body });
      if (body.model) openAiModel = body.model;
      await json(route, provider("openai", "default", openAiModel, true, true, true, "high", 30));
      return;
    }

    if (path.startsWith("/api/admin/runtime/secrets/") && request.method() === "PUT") {
      patches.push({ path, body: request.postDataJSON() });
      await json(route, { key: decodeURIComponent(path.split("/").pop() ?? ""), configured: true });
      return;
    }

    if (path === "/api/maps") mapRequests += 1;
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  return { patches, mapRequests: () => mapRequests };
}

test("runtime overview uses the full admin shell without loading match directory data", async ({ page }) => {
  const harness = await mockRuntimeAdmin(page);
  await page.goto("/admin/runtime");

  await expect(page.getByRole("heading", { name: "控制台概览" })).toBeVisible();
  await expect(page.getByText("认证方式状态", { exact: true })).toBeVisible();
  await expect(page.getByText("AI 提供商状态", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /认证配置/ })).toHaveAttribute("href", "/admin/runtime/auth");
  await expect(page.getByRole("link", { name: /AI 提供商/ })).toHaveAttribute("href", "/admin/runtime/ai-providers");
  expect(harness.mapRequests()).toBe(0);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("authentication page hot-switches Steam through the runtime settings API", async ({ page }) => {
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

test("AI providers page edits the model and keeps provider controls visible", async ({ page }) => {
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

  await expect.poll(() => harness.patches.some((entry) => entry.path.includes("/ai-providers/openai/default"))).toBe(true);
  const update = harness.patches.find((entry) => entry.path === "/api/admin/runtime/ai-providers/openai/default");
  expect(update?.body).toMatchObject({ model: "gpt-5.6-terra-admin-test" });
  await expect(page.getByText(/AI 提供商配置已更新，仅影响后续推理请求/)).toBeVisible();
});

function setting(key: string, value: unknown) {
  return {
    key,
    value,
    value_type: typeof value === "boolean" ? "BOOLEAN" : "STRING",
    category: "auth",
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

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}
