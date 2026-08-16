"""Local CLI for the official WeChat ClawBot channel (no OpenClaw required).

Usage:
    python tools\\wechat_clawbot.py login
    python tools\\wechat_clawbot.py status
    python tools\\wechat_clawbot.py send "message"
    python tools\\wechat_clawbot.py pause
    python tools\\wechat_clawbot.py resume
"""

import argparse
import asyncio
import shutil
import subprocess
from datetime import UTC, datetime

from app.config import get_settings
from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.models import WeChatAccount
from app.providers.wechat_clawbot.storage import WeChatClawBotStore

QR_POLL_TIMEOUT_SECONDS = 45.0
LOGIN_TIMEOUT_SECONDS = 300.0
MAX_QR_REFRESHES = 2


async def login(timeout_seconds: float = LOGIN_TIMEOUT_SECONDS) -> int:
    settings = get_settings()
    store = WeChatClawBotStore(settings.wechat_clawbot_state_dir)
    client = WeChatClawBotClient(
        base_url=settings.wechat_clawbot_base_url,
        bot_agent=settings.wechat_clawbot_bot_agent,
        timeout_seconds=settings.wechat_clawbot_timeout_seconds,
        long_poll_timeout_seconds=settings.wechat_clawbot_long_poll_timeout_seconds,
    )
    try:
        login_start = datetime.now(UTC)
        qr = await client.start_qr_login()
        _display_qr(qr.qrcode_url)
        poll_base_url = settings.wechat_clawbot_base_url
        verify_code: str | None = None
        refreshes = 0
        while (datetime.now(UTC) - login_start).total_seconds() < timeout_seconds:
            status = await client.poll_qr_status(
                qr.qrcode,
                verify_code=verify_code,
                base_url=poll_base_url,
                timeout_seconds=QR_POLL_TIMEOUT_SECONDS,
            )
            if status.status == "wait":
                continue
            if status.status == "scaned":
                print("📱 已扫码，请在手机上确认授权...")
                continue
            if status.status == "scaned_but_redirect":
                if status.redirect_host:
                    poll_base_url = f"https://{status.redirect_host}"
                    print(f"🌐 切换到服务节点 {poll_base_url}")
                continue
            if status.status == "need_verifycode":
                verify_code = (await asyncio.to_thread(input, "请输入微信返回的验证码: ")).strip()
                if not verify_code:
                    print("未输入验证码，终止登录。")
                    return 1
                continue
            if status.status == "verify_code_blocked":
                print("❌ 验证码输入次数过多，请稍后重新运行 login。")
                return 1
            if status.status in {"expired", "binded_redirect"}:
                if status.status == "binded_redirect":
                    print("ℹ 微信端显示该机器人已绑定到本机，本地已有凭证可继续使用。")
                    return 0
                if refreshes >= MAX_QR_REFRESHES:
                    print("❌ 二维码多次过期，请重新运行 login。")
                    return 1
                refreshes += 1
                print("⏳ 二维码已过期，正在刷新...")
                qr = await client.start_qr_login()
                _display_qr(qr.qrcode_url)
                verify_code = None
                continue
            if status.status == "confirmed":
                if not status.bot_token or not status.account_id:
                    print("❌ 登录确认但服务器未返回 bot token / bot id。")
                    return 1
                store.save_account(
                    WeChatAccount(
                        account_id=status.account_id,
                        token=status.bot_token,
                        base_url=status.base_url or settings.wechat_clawbot_base_url,
                        user_id=status.user_id,
                        created_at=datetime.now(UTC),
                    )
                )
                print("✅ 微信 ClawBot 绑定成功。")
                print(f"   账号: {status.account_id}")
                print("   运行中的 runtime 会在下个轮询周期自动接入；如需立即生效请重启应用。")
                return 0
        print("❌ 登录超时，请重新运行 login。")
        return 1
    finally:
        await client.close()


async def status() -> int:
    settings = get_settings()
    store = WeChatClawBotStore(settings.wechat_clawbot_state_dir)
    accounts = list(store.accounts())
    print(f"WECHAT_CLAWBOT_ENABLED={settings.wechat_clawbot_enabled}")
    print(f"已绑定账号: {len(accounts)}")
    for account in accounts:
        print(
            f"  - {account.account_id}"
            f" | user={account.user_id or '首次私聊后自动记录'}"
            f" | base={account.base_url}"
        )
    print(f"决策通知: {'开启' if store.decision_notifications_enabled() else '暂停'}")
    return 0


async def send(text: str) -> int:
    settings = get_settings()
    store = WeChatClawBotStore(settings.wechat_clawbot_state_dir)
    accounts = list(store.accounts())
    if not accounts:
        print("没有已绑定的微信账号，请先运行 login。")
        return 1
    client = WeChatClawBotClient(
        base_url=settings.wechat_clawbot_base_url,
        bot_agent=settings.wechat_clawbot_bot_agent,
        timeout_seconds=settings.wechat_clawbot_timeout_seconds,
        long_poll_timeout_seconds=settings.wechat_clawbot_long_poll_timeout_seconds,
    )
    try:
        for account in accounts:
            if not account.user_id:
                print(
                    f"账号 {account.account_id} 还没有私聊记录，"
                    "无法主动发送；先给它发一条微信消息。"
                )
                continue
            await client.send_text(
                account,
                to_user_id=account.user_id,
                text=text,
                context_token=account.context_token,
            )
            print(f"已发送到 {account.account_id}")
    finally:
        await client.close()
    return 0


def _display_qr(qrcode_url: str) -> None:
    print("\n用手机微信扫描下面的二维码，或打开链接后用手机微信扫码:")
    print(qrcode_url)
    try:
        npx = shutil.which("npx")
        if npx is None:
            return False
        completed = subprocess.run(  # noqa: S603 - resolved executable, no shell
            [npx, "-y", "qrcode-terminal", qrcode_url],
            check=False,
            timeout=120,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and completed.stdout:
            print(completed.stdout)
        else:
            print("(终端二维码渲染不可用，请使用上面的链接)")
    except Exception:
        print("(终端二维码渲染不可用，请使用上面的链接)")


def _pause(enabled: bool) -> int:
    settings = get_settings()
    store = WeChatClawBotStore(settings.wechat_clawbot_state_dir)
    store.set_decision_notifications(enabled)
    print("已" + ("恢复" if enabled else "暂停") + " AI 决策微信通知。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WeChat ClawBot direct channel CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login")
    sub.add_parser("status")
    send_parser = sub.add_parser("send")
    send_parser.add_argument("text")
    sub.add_parser("pause")
    sub.add_parser("resume")
    args = parser.parse_args()

    if args.command == "login":
        return asyncio.run(login())
    if args.command == "status":
        return asyncio.run(status())
    if args.command == "send":
        return asyncio.run(send(args.text))
    if args.command == "pause":
        return _pause(False)
    if args.command == "resume":
        return _pause(True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
