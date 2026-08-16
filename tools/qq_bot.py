"""Local CLI for the QQ Bot channel (harness-installed official SDK).

Usage:
    python -m tools.qq_bot login
    python -m tools.qq_bot status
    python -m tools.qq_bot send "message" --target c2c:<openid>
    python -m tools.qq_bot send "message" --target group:<group_openid>
    python -m tools.qq_bot send "message" --all
    python -m tools.qq_bot pause
    python -m tools.qq_bot resume
    python -m tools.qq_bot logout
"""

import argparse
import asyncio
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from app.config import get_settings
from app.providers.qq_bot.bridge_client import QQBridgeClient
from app.providers.qq_bot.bridge_runner import (
    resolve_qq_connector_index,
)
from app.providers.qq_bot.models import QQContact, parse_qq_target_entries
from app.providers.qq_bot.storage import QQBotStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGIN_SCRIPT = PROJECT_ROOT / "tools" / "qq_bot_login.mjs"


def _store(settings):
    return QQBotStore(settings.qq_bot_state_dir)


def _ensure_env_credentials(settings) -> None:
    store = _store(settings)
    if store.accounts():
        return
    app_id = settings.qq_bot_app_id.get_secret_value() if settings.qq_bot_app_id else None
    app_secret = (
        settings.qq_bot_app_secret.get_secret_value() if settings.qq_bot_app_secret else None
    )
    if not app_id or not app_secret:
        return
    from datetime import UTC, datetime

    from app.providers.qq_bot.models import QQBotAccount

    store.save_account(
        QQBotAccount(
            app_id=app_id,
            app_secret=app_secret,
            created_at=datetime.now(UTC),
        )
    )


def login() -> int:
    settings = get_settings()
    node = _node_bin()
    if node is None:
        print("❌ 未找到 Node.js。QQ Bot 桥接和扫码绑定都需要 Node.js >= 18。")
        return 1
    connector_index = resolve_qq_connector_index(settings)
    if not connector_index.is_file():
        print(
            "❌ 未找到 QQ 扫码绑定 SDK。\n"
            f"   查找路径: {connector_index}\n"
            "   可设置 QQ_BOT_SDK_ROOT，或在项目目录执行:\n"
            "   npm install --prefix qqbot_bridge @tencent-connect/qqbot-connector"
        )
        return 1
    env = dict(os.environ)
    env["QQ_BOT_STATE_DIR"] = str(Path(settings.qq_bot_state_dir).resolve())
    env["QQ_BOT_CONNECTOR_INDEX"] = str(connector_index)
    print("请使用手机 QQ 扫描终端中的二维码完成机器人绑定。")
    completed = subprocess.run([node, str(LOGIN_SCRIPT)], env=env, check=False)
    if completed.returncode != 0:
        print("❌ QQ Bot 绑定失败或已取消。")
        return completed.returncode or 1
    # The Node helper writes accounts.json with default permissions; tighten
    # them before printing the summary.
    store = _store(settings)
    store.restrict_file_permissions(store.root / "accounts.json")
    print("✅ QQ Bot 绑定完成。运行中的 runtime 会自动重载账号；如未运行请重启应用。")
    return 0


def _node_bin() -> str | None:
    import shutil

    return shutil.which("node")


async def status() -> int:
    settings = get_settings()
    _ensure_env_credentials(settings)
    store = _store(settings)
    accounts = list(store.accounts())
    contacts = list(store.contacts())
    subscribed = [item for item in contacts if item.subscribed]
    configured = parse_qq_target_entries(settings.qq_bot_decision_target_entries)
    print(f"QQ_BOT_ENABLED={settings.qq_bot_enabled}")
    print(f"已绑定机器人: {len(accounts)}")
    for account in accounts:
        print(f"  - app_id={account.app_id}")
    print(f"已知会话: {len(contacts)} (订阅推送 {len(subscribed)})")
    for contact in subscribed:
        label = f" [{contact.label}]" if contact.label else ""
        print(f"  - {contact.scope}:{contact.target_id}{label}")
    for contact in configured:
        print(f"  - {contact.scope}:{contact.target_id} (配置)")
    print(f"决策通知: {'开启' if store.decision_notifications_enabled() else '暂停'}")
    try:
        client = QQBridgeClient(
            base_url=f"http://{settings.qq_bot_bridge_host}:{settings.qq_bot_bridge_port}",
            timeout_seconds=settings.qq_bot_bridge_timeout_seconds,
        )
        health = await client.health()
        gateway = "已连接" if health.gateway_connected else "未连接"
        print(f"桥接: {health.status}" + (f" · gateway={gateway}" if accounts else ""))
        await client.close()
    except Exception as exc:
        print(f"桥接: 不可用 ({type(exc).__name__}: {exc})")
    return 0


async def send(text: str, *, target: str | None, all_targets: bool) -> int:
    settings = get_settings()
    _ensure_env_credentials(settings)
    store = _store(settings)
    contacts: Sequence[QQContact] = ()
    if target:
        contacts = parse_qq_target_entries((target,))
    elif all_targets:
        configured = parse_qq_target_entries(settings.qq_bot_decision_target_entries)
        merged = {item.key: item for item in configured}
        for contact in store.subscribed_contacts():
            merged.setdefault(contact.key, contact)
        contacts = list(merged.values())
    if not contacts:
        print("没有可发送的目标。请使用 --target c2c:<openid> / --target group:<group_openid>。")
        return 1
    client = QQBridgeClient(
        base_url=f"http://{settings.qq_bot_bridge_host}:{settings.qq_bot_bridge_port}",
        timeout_seconds=settings.qq_bot_bridge_timeout_seconds,
    )
    try:
        for contact in contacts:
            message_id = await client.send_text(
                scope=contact.scope,
                target_id=contact.target_id,
                text=text,
            )
            print(f"已发送到 {contact.scope}:{contact.target_id} ({message_id})")
    finally:
        await client.close()
    return 0


def _pause(enabled: bool) -> int:
    settings = get_settings()
    store = _store(settings)
    store.set_decision_notifications(enabled)
    print("已" + ("恢复" if enabled else "暂停") + " AI 决策 QQ 通知。")
    return 0


def logout() -> int:
    settings = get_settings()
    store = _store(settings)
    accounts = list(store.accounts())
    if not accounts:
        print("没有已绑定的 QQ Bot 账号。")
        return 1
    for account in accounts:
        store.remove_account(account.app_id)
        print(f"已移除账号 {account.app_id}。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="QQ Bot direct channel CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login")
    sub.add_parser("status")
    send_parser = sub.add_parser("send")
    send_parser.add_argument("text")
    send_parser.add_argument("--target", default=None)
    send_parser.add_argument("--all", action="store_true")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("logout")
    args = parser.parse_args()

    if args.command == "login":
        return login()
    if args.command == "status":
        return asyncio.run(status())
    if args.command == "send":
        return asyncio.run(send(args.text, target=args.target, all_targets=args.all))
    if args.command == "pause":
        return _pause(False)
    if args.command == "resume":
        return _pause(True)
    if args.command == "logout":
        return logout()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
