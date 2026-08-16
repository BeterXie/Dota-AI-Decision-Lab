import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required for the QQ Bot bridge",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "tools" / "qq_bot_bridge.mjs"

FAKE_SDK = """
export class QQBot {
  constructor(opts) {
    this.opts = opts;
    this.handlers = {};
    this.sent = [];
    this.counter = 0;
  }
  on(name, fn) { (this.handlers[name] ||= []).push(fn); return this; }
  use() { return this; }
  async start() {
    setTimeout(() => (this.handlers.ready || []).forEach((fn) => fn({session_id: 'fake'})), 5);
    setTimeout(() => {
      (this.handlers.message || []).forEach((fn) => fn({}, {
        kind: 'c2c',
        senderId: 'user-openid-1',
        content: '比赛',
        messageId: 'inbound-1',
        timestamp: String(Date.now()),
        mentions: [],
      }));
    }, 30);
    return new Promise(() => {});
  }
  stop() {}
  async sendText(target, text) {
    const id = 'msg-' + (++this.counter);
    this.sent.push({ target, text, id });
    return { id, timestamp: Date.now() };
  }
}
export const messageFilter = () => async (_ctx, next) => next();
export const contentSanitizer = () => async (_ctx, next) => next();
export const mentionGate = () => async (_ctx, next) => next();
export const accessPolicy = () => async (_ctx, next) => next();
"""


def test_node_bridge_health_events_and_idempotent_send(tmp_path: Path) -> None:
    sdk_index = tmp_path / "sdk-index.mjs"
    sdk_index.write_text(FAKE_SDK, encoding="utf-8")
    accounts_path = tmp_path / "accounts.json"
    accounts_path.write_text(
        json.dumps(
            [
                {
                    "app_id": "fake-app",
                    "app_secret": "fake-secret",
                    "created_at": "2026-08-16T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "QQ_BOT_STATE_DIR": str(tmp_path),
            "QQ_BOT_SDK_INDEX": str(sdk_index),
            "QQ_BOT_BRIDGE_HOST": "127.0.0.1",
            "QQ_BOT_BRIDGE_PORT": "18091",
            "QQ_BOT_ACCOUNT_ID": "fake-app",
        }
    )
    process = subprocess.Popen(
        [shutil.which("node") or "node", str(BRIDGE_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = "http://127.0.0.1:18091"
    try:
        health = None
        for _ in range(80):
            if process.poll() is not None:
                break
            try:
                health = httpx.get(f"{base_url}/health", timeout=2).json()
                if health.get("gateway_connected"):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        assert health is not None and health["gateway_connected"] is True

        events = None
        for _ in range(80):
            events = httpx.get(f"{base_url}/events", params={"cursor": 0}, timeout=2).json()
            if events.get("cursor", 0) >= 1:
                break
            time.sleep(0.05)
        assert events is not None and events["cursor"] == 1
        assert events["events"][0]["text"] == "比赛"
        assert events["events"][0]["scope"] == "c2c"

        payload = {
            "scope": "c2c",
            "target_id": "user-openid-1",
            "text": "当前比赛",
            "idempotency_key": "smoke-key",
        }
        first = httpx.post(f"{base_url}/send", json=payload, timeout=2).json()
        second = httpx.post(f"{base_url}/send", json=payload, timeout=2).json()
        assert first["message_id"] == second["message_id"] == "msg-1"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
