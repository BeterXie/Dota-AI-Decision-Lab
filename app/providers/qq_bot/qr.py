"""Authenticated web QR login for user-owned QQ Bot accounts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.notifications.center import (
    CHANNEL_QQ,
    NotificationBindingConflict,
    NotificationCenterService,
    qq_account_destination_key,
)
from app.providers.qq_bot.bridge_client import QQBridgeClient
from app.providers.qq_bot.models import QQBotAccount
from app.providers.qq_bot.storage import QQBotStore


class QQQrBindingError(RuntimeError):
    pass


QR_SESSION_TTL_SECONDS = 300


@dataclass
class _QrSession:
    session_id: str
    owner_user_id: UUID
    expires_at: datetime | None
    payload: dict
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class QQUserQrBindingService:
    """Bridge QQ connector QR sessions to authenticated site users."""

    def __init__(
        self,
        *,
        client: QQBridgeClient,
        store: QQBotStore,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._client = client
        self._store = store
        self._center = NotificationCenterService(session_factory)
        self._sessions: dict[str, _QrSession] = {}
        self._owner_sessions: dict[UUID, str] = {}
        self._lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()

    async def start(self, owner_user_id: UUID) -> dict:
        async with self._lock:
            previous_id = self._owner_sessions.pop(owner_user_id, None)
            if previous_id is not None:
                self._sessions.pop(previous_id, None)
                try:
                    await self._client.cancel_qr_binding(previous_id)
                except Exception:
                    # The bridge may already have expired or lost the old
                    # session. It is no longer reachable from this user.
                    pass
            payload = await self._client.start_qr_binding()
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise QQQrBindingError("QQ bridge did not return a QR session id")
            session = _QrSession(
                session_id=session_id,
                owner_user_id=owner_user_id,
                expires_at=_parse_expiry(payload.get("expires_at")),
                payload=dict(payload),
            )
            self._sessions[session_id] = session
            self._owner_sessions[owner_user_id] = session_id
            return self._public_payload(session.payload)

    async def poll(
        self,
        owner_user_id: UUID,
        session_id: str,
        *,
        verify_code: str | None = None,
    ) -> dict:
        del verify_code  # QQ connector has no secondary verification-code step.
        session = await self._owned_session(owner_user_id, session_id)
        async with session.lock:
            if str(session.payload.get("status") or "").upper() == "BOUND":
                return self._public_payload(session.payload)
            if session.expires_at is not None and datetime.now(UTC) >= session.expires_at:
                session.payload = {
                    **session.payload,
                    "status": "EXPIRED",
                    "message": "二维码已过期，请重新生成",
                }
                return self._public_payload(session.payload)
            payload = await self._client.poll_qr_binding(session_id)
            status = str(payload.get("status") or "FAILED").upper()
            session.payload = dict(payload)
            session.expires_at = _parse_expiry(payload.get("expires_at")) or session.expires_at
            if status == "COMPLETED":
                try:
                    async with self._account_lock:
                        await self._complete(owner_user_id, session, payload)
                except (QQQrBindingError, NotificationBindingConflict) as exc:
                    session.payload = {
                        **payload,
                        "status": "FAILED",
                        "message": str(exc),
                    }
                else:
                    session.payload = {
                        **payload,
                        "status": "BOUND",
                        "message": "QQ 账号已绑定，通知将直接发送到该扫码账号",
                    }
            return self._public_payload(session.payload)

    async def cancel(self, owner_user_id: UUID, session_id: str) -> dict:
        session = await self._owned_session(owner_user_id, session_id)
        async with session.lock:
            payload = await self._client.cancel_qr_binding(session_id)
            session.payload = dict(payload)
            async with self._lock:
                self._sessions.pop(session_id, None)
                if self._owner_sessions.get(owner_user_id) == session_id:
                    self._owner_sessions.pop(owner_user_id, None)
            return self._public_payload(session.payload)

    async def revoke(self, owner_user_id: UUID, destination: dict) -> None:
        account_id = destination.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            return
        account = next(
            (item for item in self._store.accounts() if item.app_id == account_id),
            None,
        )
        if account is not None and account.owner_user_id == str(owner_user_id):
            self._store.remove_account(account_id)

    async def close(self) -> None:
        async with self._lock:
            session_ids = list(self._sessions)
            self._sessions.clear()
            self._owner_sessions.clear()
        for session_id in session_ids:
            try:
                await self._client.cancel_qr_binding(session_id)
            except Exception:
                pass

    async def _owned_session(self, owner_user_id: UUID, session_id: str) -> _QrSession:
        await self._purge()
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            raise QQQrBindingError("二维码会话不存在或不属于当前账号")

        return session

    async def _purge(self) -> None:
        now = datetime.now(UTC)
        async with self._lock:
            for session_id, session in list(self._sessions.items()):
                expiry = session.expires_at
                if expiry is not None and expiry + timedelta(minutes=5) <= now:
                    self._sessions.pop(session_id, None)
                    if self._owner_sessions.get(session.owner_user_id) == session_id:
                        self._owner_sessions.pop(session.owner_user_id, None)

    async def _complete(self, owner_user_id: UUID, session: _QrSession, payload: dict) -> None:
        raw = payload.get("credentials")
        if not isinstance(raw, dict):
            raise QQQrBindingError("QQ 扫码未返回账号凭据")
        app_id = raw.get("app_id")
        app_secret = raw.get("app_secret")
        user_openid = raw.get("user_openid")
        if not all(
            isinstance(item, str) and item.strip() for item in (app_id, app_secret, user_openid)
        ):
            raise QQQrBindingError("QQ 扫码未返回可用的用户标识")
        app_id = app_id.strip()
        user_openid = user_openid.strip()
        existing = next((item for item in self._store.accounts() if item.app_id == app_id), None)
        owner = str(owner_user_id)
        if existing is not None:
            if existing.owner_user_id == owner:
                pass
            elif existing.owner_user_id is None:
                raise QQQrBindingError("该 QQ Bot 账号属于旧共享配置，请使用新的用户二维码")
            else:
                raise QQQrBindingError("该 QQ Bot 账号已绑定到其他站内账号")
        previous_accounts = self._store.accounts_for_owner(owner)
        account = QQBotAccount(
            app_id=app_id,
            app_secret=app_secret,
            user_openid=user_openid,
            owner_user_id=owner,
            account_mode="USER",
            created_at=datetime.now(UTC),
        )
        self._store.save_account(account)
        try:
            await self._center.bind_user_account(
                user_id=owner_user_id,
                channel=CHANNEL_QQ,
                destination_key=qq_account_destination_key(app_id, "c2c", user_openid),
                destination={
                    "account_id": app_id,
                    "scope": "c2c",
                    "target_id": user_openid,
                    "account_mode": "USER",
                },
                label="QQ 扫码账号",
            )
        except Exception:
            self._store.remove_account(app_id)
            for previous in previous_accounts:
                self._store.save_account(previous)
            raise
        for previous in previous_accounts:
            if previous.app_id != app_id:
                self._store.remove_account(previous.app_id)
        async with self._lock:
            if self._owner_sessions.get(owner_user_id) == session.session_id:
                self._owner_sessions.pop(owner_user_id, None)

    @staticmethod
    def _public_payload(payload: dict) -> dict:
        public_keys = {
            "channel",
            "session_id",
            "status",
            "qrcode_url",
            "created_at",
            "expires_at",
            "message",
        }
        return {key: value for key, value in payload.items() if key in public_keys}


def _parse_expiry(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return datetime.now(UTC) + timedelta(seconds=QR_SESSION_TTL_SECONDS)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC) + timedelta(seconds=QR_SESSION_TTL_SECONDS)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
