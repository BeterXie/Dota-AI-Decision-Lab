// QQ Bot bridge for Dota AI Decision Lab.
//
// Loads the official @tencent-connect/qqbot-nodejs SDK from the path selected
// by the Python runtime (harness profile by default) and exposes an authenticated
// loopback HTTP API:
//   GET  /health             -> bridge/gateway status
//   GET  /events?cursor=N    -> buffered inbound messages after cursor N
//   POST /send               -> send a C2C or group text message
//
// Inbound messages are only buffered for the Python service. All command
// routing, database queries and decision rendering happen in Python.

import http from "node:http";
import crypto from "node:crypto";
import fs from "node:fs";
import { mkdir, readFile, writeFile, rename } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const stateDir = path.resolve(process.env.QQ_BOT_STATE_DIR || ".runtime/qq-bot");
const accountsPath = path.join(stateDir, "accounts.json");
const cursorDir = path.join(stateDir, "cursors");
const sdkIndex = process.env.QQ_BOT_SDK_INDEX;
if (!sdkIndex) {
  console.error("QQ_BOT_SDK_INDEX is required");
  process.exit(2);
}
const sdk = await import(pathToFileURL(sdkIndex).href);
const { QQBot, messageFilter, contentSanitizer, mentionGate, accessPolicy } = sdk;

const host = process.env.QQ_BOT_BRIDGE_HOST || "127.0.0.1";
const loopbackHosts = new Set(["127.0.0.1", "localhost", "::1"]);
if (!loopbackHosts.has(host)) {
  console.error("QQ_BOT_BRIDGE_HOST must remain loopback");
  process.exit(2);
}
const bridgeToken = process.env.QQ_BOT_BRIDGE_TOKEN || "";
if (bridgeToken.length < 32) {
  console.error("QQ_BOT_BRIDGE_TOKEN must be at least 32 characters");
  process.exit(2);
}
const port = Number(process.env.QQ_BOT_BRIDGE_PORT || 18081);
const preferredAccountId = process.env.QQ_BOT_ACCOUNT_ID || "";
const requireMention = process.env.QQ_BOT_GROUP_REQUIRE_MENTION !== "0";
const allowedC2C = splitList(process.env.QQ_BOT_ALLOWED_C2C);
const allowedGroups = splitList(process.env.QQ_BOT_ALLOWED_GROUPS);

let bot = null;
let botAbort = null;
let botStartPromise = null;
let gatewayConnected = false;
let status = "stopped";
let statusMessage = null;
let accountCount = 0;

const events = [];
// The event buffer is intentionally in-memory, but the cursor must survive a
// bridge restart. Python persists the last processed cursor per account; use
// the highest stored value so new events remain strictly after that cursor.
function loadInitialEventCursor() {
  let highest = 0;
  try {
    for (const entry of fs.readdirSync(cursorDir)) {
      if (!entry.endsWith(".json")) continue;
      try {
        const raw = JSON.parse(fs.readFileSync(path.join(cursorDir, entry), "utf8"));
        const value = raw?.event_cursor;
        if (Number.isSafeInteger(value) && value >= 0) highest = Math.max(highest, value);
      } catch {
        // Ignore an incomplete cursor file while the Python store is rotating it.
      }
    }
  } catch {
    // The cursor directory is created by the Python store after first login.
  }
  return highest;
}

let eventCursor = loadInitialEventCursor();
const MAX_EVENTS = 1000;

function splitList(raw) {
  return (raw || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function log(level, message, meta = undefined) {
  const entry = { ts: new Date().toISOString(), level, message };
  if (meta && Object.keys(meta).length) entry.meta = meta;
  console.log(JSON.stringify(entry));
}

const sdkLogger = {
  info: (message, meta) => log("info", message, meta),
  error: (message, meta) => log("error", message, meta),
  warn: (message, meta) => log("warn", message, meta),
};

function setStatus(next, message = null) {
  status = next;
  statusMessage = message;
  log("info", `bridge_status=${next}${message ? ` message=${message}` : ""}`);
}

function authorized(req) {
  const header = req.headers.authorization;
  if (typeof header !== "string" || !header.startsWith("Bearer ")) return false;
  const supplied = header.slice("Bearer ".length);
  const expectedBytes = Buffer.from(bridgeToken, "utf8");
  const suppliedBytes = Buffer.from(supplied, "utf8");
  return (
    expectedBytes.length === suppliedBytes.length &&
    crypto.timingSafeEqual(expectedBytes, suppliedBytes)
  );
}

async function readAccounts() {
  try {
    const raw = JSON.parse(await readFile(accountsPath, "utf8"));
    const accounts = Array.isArray(raw) ? raw : [];
    accountCount = accounts.filter(
      (item) => item && typeof item.app_id === "string" && typeof item.app_secret === "string",
    ).length;
    return accounts.filter(
      (item) => item && typeof item.app_id === "string" && typeof item.app_secret === "string",
    );
  } catch (error) {
    accountCount = 0;
    return [];
  }
}

function safeTimestamp(raw) {
  if (raw === undefined || raw === null) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function enqueueMessage(msg) {
  const scope = msg.kind === "c2c" ? "c2c" : "group";
  const mentions = Array.isArray(msg.mentions)
    ? msg.mentions
        .filter((mention) => mention && typeof mention === "object")
        .map((mention) => mention.id || mention.user_openid || mention.member_openid || "")
        .filter(Boolean)
    : [];
  const botMentioned = Array.isArray(msg.mentions)
    ? msg.mentions.some((mention) => mention && (mention.is_you === true || mention.bot === true))
    : false;
  const event = {
    event_type: "MESSAGE",
    event_cursor: ++eventCursor,
    scope,
    target_id: scope === "c2c" ? msg.senderId : msg.groupOpenid,
    sender_id: msg.senderId,
    message_id: msg.messageId,
    text: msg.content || "",
    sender_name: msg.senderName || null,
    bot_mentioned: botMentioned,
    mentions,
    timestamp: safeTimestamp(msg.timestamp),
  };
  events.push(event);
  if (events.length > MAX_EVENTS) events.shift();
  log("info", "qq_event_buffered", {
    cursor: event.event_cursor,
    scope: event.scope,
    target_id: event.target_id,
  });
}

function enqueueFriendAdd(raw) {
  const openid = firstString(
    raw?.openid,
    raw?.open_id,
    raw?.user_openid,
    raw?.userOpenid,
    raw?.sender_id,
    raw?.author?.openid,
    raw?.author?.user_openid,
  );
  if (!openid) return;
  const callbackData = firstString(
    raw?.scene_param,
    raw?.sceneParam,
    raw?.callback_data,
    raw?.callbackData,
  );
  const event = {
    event_type: "FRIEND_ADD",
    event_cursor: ++eventCursor,
    scope: "c2c",
    target_id: openid,
    sender_id: openid,
    message_id: null,
    text: "",
    scene_param: callbackData || null,
    sender_name: firstString(raw?.author?.nick, raw?.author?.nickname, raw?.nickname) || null,
    bot_mentioned: false,
    mentions: [],
    timestamp: safeTimestamp(
      (() => {
        const value = Number(raw?.timestamp || 0);
        return value > 0 && value < 1_000_000_000_000 ? value * 1000 : value;
      })(),
    ),
  };
  events.push(event);
  if (events.length > MAX_EVENTS) events.shift();
  log("info", "qq_friend_added", {
    cursor: event.event_cursor,
    scene: raw?.scene || null,
    has_callback_data: Boolean(callbackData),
  });
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function buildBot(account) {
  const controller = new AbortController();
  const instance = new QQBot({
    appId: account.app_id,
    appSecret: account.app_secret,
    accountId: account.app_id,
    logger: sdkLogger,
    userAgent: "Dota-AI-Decision-Lab/0.1.0",
    sessionPersistence: {
      load: () => {
        try {
          const file = path.join(stateDir, "gateway-session.json");
          if (!fs.existsSync(file)) return null;
          return JSON.parse(fs.readFileSync(file, "utf8"));
        } catch {
          return null;
        }
      },
      save: (session) => {
        try {
          fs.mkdirSync(stateDir, { recursive: true });
          const file = path.join(stateDir, "gateway-session.json");
          const temp = `${file}.tmp`;
          fs.writeFileSync(temp, JSON.stringify(session));
          fs.renameSync(temp, file);
        } catch (error) {
          log("warn", "session_save_failed", { error: String(error) });
        }
      },
      clear: () => {
        try {
          fs.rmSync(path.join(stateDir, "gateway-session.json"), { force: true });
        } catch {
          // Session cleanup is best-effort.
        }
      },
    },
  });

  instance.on("ready", (data) => {
    gatewayConnected = true;
    setStatus("READY");
    log("info", "gateway_ready", { sessionId: data?.session_id || null });
  });
  instance.on("resumed", () => {
    gatewayConnected = true;
    setStatus("READY");
  });
  instance.on("error", (error) => {
    setStatus("DEGRADED", String(error?.message || error));
  });
  instance.on("message", (_ctx, msg) => {
    try {
      enqueueMessage(msg);
    } catch (error) {
      log("error", "message_buffer_failed", { error: String(error) });
    }
  });
  instance.on("rawEvent", (ctx) => {
    if (ctx?.eventType !== "FRIEND_ADD") return;
    try {
      enqueueFriendAdd(ctx.data || ctx.payload || ctx);
    } catch (error) {
      log("error", "friend_add_buffer_failed", { error: String(error) });
    }
  });

  const policy = {};
  if (allowedC2C.length) {
    // Keep pairing commands visible to Python even when an operator has an
    // allowlist. The application verifies the one-time code and then applies
    // the allowlist to every other private-chat command; filtering here would
    // make a new user unable to complete the binding handshake.
    const pairingCommand = (ctx) => {
      const content = ctx?.message?.content;
      return typeof content === "string" &&
        /^(绑定|绑定通知|bind|\/bind)\s+\S+/iu.test(content.trim());
    };
    policy.c2c = { mode: "allowlist", allow: [...allowedC2C, pairingCommand] };
  }
  if (allowedGroups.length) policy.group = { mode: "allowlist", allow: allowedGroups };
  if (Object.keys(policy).length) instance.use(accessPolicy(policy));
  instance.use(messageFilter({ skipSelfEcho: true, dedup: { windowMs: 5000, maxSize: 1000 } }));
  instance.use(contentSanitizer({ collapseWhitespace: true }));
  instance.use(mentionGate({ requireMentionInGroup: requireMention }));

  setStatus("STARTING");
  botStartPromise = instance
    .start(controller.signal)
    .then(() => {
      gatewayConnected = false;
      setStatus("STOPPED");
    })
    .catch((error) => {
      gatewayConnected = false;
      setStatus("DEGRADED", String(error?.message || error));
      log("error", "bot_start_failed", { error: String(error?.stack || error) });
    });
  bot = instance;
  botAbort = controller;
  log("info", "bot_started", { appId: account.app_id });
}

async function stopBot() {
  const current = bot;
  bot = null;
  if (!current) return;
  try {
    botAbort?.abort();
    current.stop();
    await botStartPromise;
  } catch {
    // A stopped bridge must not propagate shutdown races.
  } finally {
    gatewayConnected = false;
    botAbort = null;
    botStartPromise = null;
  }
}

async function startFromAccounts() {
  const accounts = await readAccounts();
  if (!accounts.length) {
    setStatus("ACTION_REQUIRED", "run: python -m tools.qq_bot login");
    return;
  }
  const account =
    accounts.find((item) => item.app_id === preferredAccountId) || accounts[0];
  await stopBot();
  if (!bot) buildBot(account);
}

function sendJson(res, code, body) {
  const payload = JSON.stringify(body);
  res.writeHead(code, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function readJsonBody(req, limit = 1024 * 1024) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new Error("request body too large");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function sendMessage(body) {
  if (!bot || !gatewayConnected) {
    const error = new Error("QQ bridge is not connected to the QQ gateway");
    error.statusCode = 503;
    throw error;
  }
  const target = {
    scope: body.scope === "group" ? "group" : "c2c",
    targetId: body.target_id,
  };
  if (body.msg_id) target.msgId = body.msg_id;
  const response = await bot.sendText(target, body.text);
  return {
    message_id: response?.id || null,
    timestamp: response?.timestamp || null,
  };
}

const outboxDir = path.join(stateDir, "outbox");
async function idempotentSend(body) {
  if (!body.idempotency_key) return sendMessage(body);
  const digest = crypto
    .createHash("sha256")
    .update(body.idempotency_key)
    .digest("hex")
    .slice(0, 48);
  const file = path.join(outboxDir, `${digest}.json`);
  try {
    return JSON.parse(await readFile(file, "utf8"));
  } catch {
    // First send for this idempotency key.
  }
  const result = await sendMessage(body);
  await mkdir(outboxDir, { recursive: true });
  const temp = `${file}.tmp`;
  await writeFile(temp, JSON.stringify(result));
  await rename(temp, file);
  return result;
}

async function createShareLink(body) {
  if (!bot || !gatewayConnected) {
    const error = new Error("QQ bridge is not connected to the QQ gateway");
    error.statusCode = 503;
    throw error;
  }
  const callbackData = typeof body.callback_data === "string" ? body.callback_data.trim() : "";
  if (!callbackData || callbackData.length > 32) {
    const error = new Error("callback_data must be 1-32 characters");
    error.statusCode = 400;
    throw error;
  }
  const response = await bot.api.post("/v2/generate_url_link", {
    callback_data: callbackData,
  });
  if (typeof response?.retcode === "number" && response.retcode !== 0) {
    throw new Error(
      `QQ API share-link request failed: retcode=${response.retcode} ` +
      `message=${typeof response.msg === "string" ? response.msg : "(none)"}`,
    );
  }
  // The current API wraps the link as data.url, while the published API
  // contract documents url_link. Accept both official response shapes.
  const urlLink = response?.data?.url || response?.url_link || response?.data?.url_link;
  if (typeof urlLink !== "string" || !urlLink) {
    throw new Error("QQ API share-link response is missing the generated URL");
  }
  return { url_link: urlLink };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${host}:${port}`);
  try {
    if (!authorized(req)) {
      sendJson(res, 401, { error: "unauthorized" });
      return;
    }
    if (req.method === "GET" && url.pathname === "/health") {
      sendJson(res, 200, {
        ok: gatewayConnected,
        status,
        message: statusMessage,
        account_count: accountCount,
        gateway_connected: gatewayConnected,
        buffered_events: events.length,
      });
      return;
    }
    if (req.method === "GET" && url.pathname === "/events") {
      const cursor = Number(url.searchParams.get("cursor") || 0);
      const outgoing = events.filter((event) => event.event_cursor > cursor);
      sendJson(res, 200, { events: outgoing, cursor: eventCursor });
      return;
    }
    if (req.method === "POST" && url.pathname === "/send") {
      const body = await readJsonBody(req);
      if (!body.scope || !body.target_id || typeof body.text !== "string" || !body.text.trim()) {
        sendJson(res, 400, { error: "scope, target_id and non-empty text are required" });
        return;
      }
      const result = await idempotentSend(body);
      sendJson(res, 200, result);
      return;
    }
    if (req.method === "POST" && url.pathname === "/share-link") {
      const body = await readJsonBody(req);
      const result = await createShareLink(body);
      sendJson(res, 200, result);
      return;
    }
    sendJson(res, 404, { error: "not found" });
  } catch (error) {
    const statusCode = error.statusCode || 500;
    if (statusCode >= 500) log("error", "http_request_failed", { error: String(error?.stack || error) });
    sendJson(res, statusCode, { error: String(error?.message || error) });
  }
});

server.listen(port, host, () => {
  log("info", "bridge_http_listening", { host, port, sdkIndex });
});

async function reloadAccounts() {
  try {
    await startFromAccounts();
  } catch (error) {
    setStatus("DEGRADED", String(error?.message || error));
    log("error", "account_reload_failed", { error: String(error?.stack || error) });
  }
}

await reloadAccounts();
fs.watchFile(accountsPath, { interval: 2000 }, async (current, previous) => {
  if (
    current.mtimeMs !== previous.mtimeMs ||
    current.size !== previous.size ||
    !current.isFile()
  ) {
    await reloadAccounts();
  }
});

async function shutdown(signal) {
  log("info", "bridge_shutdown", { signal });
  await stopBot();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
