"""Authenticated web QR login for user-owned WeChat ClawBot accounts."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications.center import (
    CHANNEL_WECHAT,
    NotificationBindingConflict,
    NotificationCenterService,
    wechat_destination_key,
)
from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.models import WeChatAccount
from app.providers.wechat_clawbot.storage import WeChatClawBotStore

QR_TTL_SECONDS = 300


class WeChatQrBindingError(RuntimeError):
    pass


@dataclass
class _QrSession:
    session_id: str
    owner_user_id: UUID
    qrcode: str
    qrcode_url: str
    poll_base_url: str
    created_at: datetime
    expires_at: datetime
    status: str = "WAITING"
    message: str | None = None
    verify_code: str | None = None
    account_id: str | None = None
    user_id: str | None = None
    binding_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WeChatUserQrBindingService:
    """Own one short-lived QR login session per authenticated user.

    The iLink token is written only to ``WeChatClawBotStore`` after the QR
    status reaches ``confirmed``. It is never included in an HTTP response or
    database binding.
    """

    def __init__(
        self,
        *,
        client: WeChatClawBotClient,
        store: WeChatClawBotStore,
        session_factory: async_sessionmaker[AsyncSession],
        ttl_seconds: int = QR_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._store = store
        self._center = NotificationCenterService(session_factory)
        self._ttl_seconds = max(60, ttl_seconds)
        self._sessions: dict[str, _QrSession] = {}
        self._lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()

    async def start(self, owner_user_id: UUID) -> dict:
        await self._purge()
        # A second click replaces the user's previous unfinished login. The
        # provider QR itself remains valid only for the short session window.
        async with self._lock:
            for key, session in list(self._sessions.items()):
                if session.owner_user_id == owner_user_id:
                    session.status = "CANCELLED"
                    self._sessions.pop(key, None)
            qr = await self._client.start_qr_login()
            now = datetime.now(UTC)
            session = _QrSession(
                session_id=secrets.token_urlsafe(18),
                owner_user_id=owner_user_id,
                qrcode=qr.qrcode,
                qrcode_url=qr.qrcode_url,
                poll_base_url=self._client.base_url(),
                created_at=now,
                expires_at=now + timedelta(seconds=self._ttl_seconds),
            )
            self._sessions[session.session_id] = session
        return self._payload(session)

    async def poll(
        self,
        owner_user_id: UUID,
        session_id: str,
        *,
        verify_code: str | None = None,
    ) -> dict:
        session = await self._owned_session(owner_user_id, session_id)
        async with session.lock:
            now = datetime.now(UTC)
            if session.status in {"BOUND", "FAILED", "EXPIRED", "CANCELLED"}:
                return self._payload(session)
            if now >= session.expires_at:
                session.status = "EXPIRED"
                session.message = "二维码已过期，请重新生成"
                return self._payload(session)
            if verify_code is not None:
                session.verify_code = verify_code.strip() or None
            status = await self._client.poll_qr_status(
                session.qrcode,
                verify_code=session.verify_code,
                base_url=session.poll_base_url,
                timeout_seconds=self._client.long_poll_timeout_seconds,
            )
            if status.base_url:
                session.poll_base_url = status.base_url
            elif status.redirect_host:
                session.poll_base_url = f"https://{status.redirect_host}"
            if status.status == "wait":
                session.status = "WAITING"
                session.message = None
            elif status.status == "scaned":
                session.status = "SCANNED"
                session.message = "已扫码，请在微信中确认授权"
            elif status.status == "need_verifycode":
                session.status = "NEED_VERIFY_CODE"
                session.message = "请输入微信返回的验证码"
            elif status.status == "scaned_but_redirect":
                session.status = "SCANNED"
                session.message = "已扫码，正在切换微信服务节点"
            elif status.status == "verify_code_blocked":
                session.status = "FAILED"
                session.message = "验证码尝试次数过多，请重新生成二维码"
            elif status.status in {"expired", "binded_redirect"}:
                session.status = "EXPIRED" if status.status == "expired" else "FAILED"
                session.message = (
                    "二维码已过期，请重新生成"
                    if status.status == "expired"
                    else "此微信账号已绑定到其他运行实例"
                )
            elif status.status == "confirmed":
                try:
                    async with self._account_lock:
                        await self._complete(session, status)
                except NotificationBindingConflict as exc:
                    session.status = "FAILED"
                    session.message = str(exc)
            else:
                session.status = "FAILED"
                session.message = f"微信登录返回未知状态: {status.status}"
            return self._payload(session)

    async def cancel(self, owner_user_id: UUID, session_id: str) -> dict:
        session = await self._owned_session(owner_user_id, session_id)
        async with session.lock:
            session.status = "CANCELLED"
            session.message = "已取消扫码绑定"
            return self._payload(session)

    async def revoke(self, owner_user_id: UUID, destination: dict) -> None:
        account_id = destination.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            return
        account = next(
            (item for item in self._store.accounts() if item.account_id == account_id),
            None,
        )
        if account is not None and account.owner_user_id == str(owner_user_id):
            self._store.remove_account(account_id)

    async def close(self) -> None:
        async with self._lock:
            for session in self._sessions.values():
                session.status = "CANCELLED"
            self._sessions.clear()

    async def _complete(self, session: _QrSession, status) -> None:
        if not status.bot_token or not status.account_id or not status.user_id:
            session.status = "FAILED"
            session.message = "登录确认成功但缺少微信账号信息"
            return
        owner = str(session.owner_user_id)
        existing = next(
            (item for item in self._store.accounts() if item.account_id == status.account_id),
            None,
        )
        if existing is not None and existing.owner_user_id not in {None, owner}:
            session.status = "FAILED"
            session.message = "该微信 ClawBot 账号已绑定到其他站内账号"
            return
        if existing is not None and existing.owner_user_id is None:
            session.status = "FAILED"
            session.message = "该微信 ClawBot 账号属于旧共享配置，请使用新的用户二维码"
            return
        # Keep one user-owned account per site user/channel. Write the new
        # credential before retiring the old one, so a database conflict or
        # transient write failure does not strand the user without an account.
        previous_accounts = self._store.accounts_for_owner(owner)
        account = WeChatAccount(
            account_id=status.account_id,
            token=status.bot_token,
            base_url=status.base_url or session.poll_base_url,
            owner_user_id=owner,
            account_mode="USER",
            user_id=status.user_id,
            created_at=datetime.now(UTC),
        )
        self._store.save_account(account)
        try:
            binding = await self._center.bind_user_account(
                user_id=session.owner_user_id,
                channel=CHANNEL_WECHAT,
                destination_key=wechat_destination_key(account.account_id, account.user_id),
                destination={
                    "account_id": account.account_id,
                    "user_id": account.user_id,
                    "account_mode": "USER",
                },
                label="微信扫码账号",
            )
        except Exception:
            self._store.remove_account(account.account_id)
            for previous in previous_accounts:
                self._store.save_account(previous)
            raise
        for previous in previous_accounts:
            if previous.account_id != account.account_id:
                self._store.remove_account(previous.account_id)
        session.status = "BOUND"
        session.message = "微信账号已绑定，通知将直接发送到该扫码账号"
        session.account_id = account.account_id
        session.user_id = account.user_id
        session.binding_id = str(binding.id)

    async def _owned_session(self, owner_user_id: UUID, session_id: str) -> _QrSession:
        await self._purge()
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            raise WeChatQrBindingError("二维码会话不存在或不属于当前账号")
        return session

    async def _purge(self) -> None:
        now = datetime.now(UTC)
        async with self._lock:
            for key, session in list(self._sessions.items()):
                if session.expires_at <= now and session.status not in {"BOUND", "FAILED"}:
                    session.status = "EXPIRED"
                    session.message = "二维码已过期，请重新生成"
                if session.expires_at + timedelta(minutes=5) <= now:
                    self._sessions.pop(key, None)

    @staticmethod
    def _payload(session: _QrSession) -> dict:
        return {
            "channel": CHANNEL_WECHAT,
            "session_id": session.session_id,
            "status": session.status,
            "qrcode_url": session.qrcode_url,
            "created_at": session.created_at,
            "expires_at": session.expires_at,
            "message": session.message,
            "account_id": session.account_id,
            "user_id": session.user_id,
            "binding_id": session.binding_id,
        }
