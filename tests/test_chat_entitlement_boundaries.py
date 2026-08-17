from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.db import Base
from app.entitlements import AI_DECISIONS_ENTITLEMENT
from app.notifications.center import CHANNEL_QQ, qq_destination_key
from app.notifications.secure_center import NotificationCenterService
from app.providers.qq_bot import user_service as qq_user_service
from app.providers.qq_bot.models import QQInboundMessage
from app.providers.wechat_clawbot import user_service as wechat_user_service
from app.providers.wechat_clawbot.models import MESSAGE_TYPE_USER, WeChatInboundMessage
from app.runtime.health import HealthRegistry
from app.web import create_app


class _ChatCenter:
    def __init__(self, user_id: UUID | None) -> None:
        self.user_id = user_id
        self.preference_calls: list[tuple[str, str, bool]] = []

    async def bound_active_user_id(self, *, channel: str, destination_key: str) -> UUID | None:
        return self.user_id

    async def set_preference_for_destination(
        self,
        *,
        channel: str,
        destination_key: str,
        enabled: bool,
    ) -> bool:
        self.preference_calls.append((channel, destination_key, enabled))
        return self.user_id is not None


class _Entitlements:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, str]] = []

    async def has_entitlement(self, user_id: UUID, entitlement: str) -> bool:
        self.calls.append((user_id, entitlement))
        return self.allowed


class _QQClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, **kwargs) -> str:
        self.sent.append(kwargs)
        return "qq-message"

    async def close(self) -> None:
        return None


class _WeChatClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, account, **kwargs) -> str:
        self.sent.append({"account": account, **kwargs})
        return "wechat-message"

    async def close(self) -> None:
        return None


def _qq_message(text: str, *, scope: str = "c2c") -> QQInboundMessage:
    return QQInboundMessage(
        event_cursor=1,
        scope=scope,  # type: ignore[arg-type]
        target_id="qq-user" if scope == "c2c" else "qq-group",
        sender_id="qq-user",
        message_id="qq-in-1",
        text=text,
        bot_mentioned=True,
    )


def _wechat_message(text: str) -> WeChatInboundMessage:
    return WeChatInboundMessage(
        message_id=1,
        from_user_id="wechat-user",
        message_type=MESSAGE_TYPE_USER,
        text=text,
    )


@pytest.mark.asyncio
async def test_secure_center_resolves_only_active_verified_binding_owner() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with factory.begin() as session:
            user = UserAccountRecord(
                email="chat@example.com",
                email_verified_at=now,
                last_login_at=now,
                created_at=now,
            )
            session.add(user)
            await session.flush()
            user_id = user.id

        center = NotificationCenterService(factory)
        code, _ = await center.create_pairing_code(user_id, CHANNEL_QQ)
        await center.consume_pairing_code(
            channel=CHANNEL_QQ,
            code=code,
            destination_key=qq_destination_key("c2c", "qq-user"),
            destination={"scope": "c2c", "target_id": "qq-user"},
        )
        assert (
            await center.bound_active_user_id(
                channel=CHANNEL_QQ,
                destination_key=qq_destination_key("c2c", "qq-user"),
            )
            == user_id
        )

        async with factory.begin() as session:
            stored = await session.get(UserAccountRecord, user_id)
            assert stored is not None
            stored.disabled_at = datetime.now(UTC)
        assert (
            await center.bound_active_user_id(
                channel=CHANNEL_QQ,
                destination_key=qq_destination_key("c2c", "qq-user"),
            )
            is None
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_qq_ai_query_requires_bound_user_and_ai_entitlement(monkeypatch) -> None:
    client = _QQClient()
    service = qq_user_service.UserScopedQQBotService(
        client=client,
        store=object(),
        session_factory=object(),
        jobs=object(),
    )
    center = _ChatCenter(None)
    entitlements = _Entitlements(False)
    service._notification_center = center
    service._entitlements = entitlements

    called = False

    async def premium_reply(*args, **kwargs) -> str:
        nonlocal called
        called = True
        return "premium-decision"

    monkeypatch.setattr(qq_user_service, "command_reply", premium_reply)
    await service._handle_message(object(), _qq_message("为什么买 OG"))
    assert "需要先绑定登录账号" in client.sent[-1]["text"]
    assert called is False

    user_id = uuid4()
    center.user_id = user_id
    await service._handle_message(object(), _qq_message("为什么买 OG"))
    assert "没有 AI 决策权限" in client.sent[-1]["text"]
    assert entitlements.calls[-1] == (user_id, AI_DECISIONS_ENTITLEMENT)
    assert called is False

    entitlements.allowed = True
    await service._handle_message(object(), _qq_message("为什么买 OG"))
    assert client.sent[-1]["text"] == "premium-decision"
    assert called is True


@pytest.mark.asyncio
async def test_qq_group_cannot_query_premium_ai_decisions(monkeypatch) -> None:
    client = _QQClient()
    service = qq_user_service.UserScopedQQBotService(
        client=client,
        store=object(),
        session_factory=object(),
        jobs=object(),
        group_require_mention=True,
    )
    service._notification_center = _ChatCenter(uuid4())
    service._entitlements = _Entitlements(True)

    async def should_not_run(*args, **kwargs) -> str:
        raise AssertionError("group premium query reached decision command")

    monkeypatch.setattr(qq_user_service, "command_reply", should_not_run)
    await service._handle_message(object(), _qq_message("为什么买 OG", scope="group"))
    assert "仅支持已绑定的 QQ 私聊" in client.sent[-1]["text"]


@pytest.mark.asyncio
async def test_qq_pause_and_resume_update_user_notification_preference() -> None:
    client = _QQClient()
    service = qq_user_service.UserScopedQQBotService(
        client=client,
        store=object(),
        session_factory=object(),
        jobs=object(),
    )
    center = _ChatCenter(uuid4())
    service._notification_center = center

    await service._handle_message(object(), _qq_message("暂停 AI 通知"))
    await service._handle_message(object(), _qq_message("恢复通知"))

    assert [call[2] for call in center.preference_calls] == [False, True]
    assert "已关闭" in client.sent[-2]["text"]
    assert "已开启" in client.sent[-1]["text"]


@pytest.mark.asyncio
async def test_wechat_ai_query_and_pause_use_bound_account_state(monkeypatch) -> None:
    client = _WeChatClient()
    service = wechat_user_service.UserScopedWeChatClawBotService(
        client=client,
        store=object(),
        session_factory=object(),
        jobs=object(),
    )
    center = _ChatCenter(None)
    entitlements = _Entitlements(False)
    service._notification_center = center
    service._entitlements = entitlements
    account = SimpleNamespace(account_id="bot-account")

    called = False

    async def premium_reply(*args, **kwargs) -> str:
        nonlocal called
        called = True
        return "wechat-premium"

    monkeypatch.setattr(wechat_user_service, "command_reply", premium_reply)
    await service._handle_message(object(), account, _wechat_message("为什么买 OG"))
    assert "需要先绑定登录账号" in client.sent[-1]["text"]
    assert called is False

    user_id = uuid4()
    center.user_id = user_id
    entitlements.allowed = True
    await service._handle_message(object(), account, _wechat_message("为什么买 OG"))
    assert client.sent[-1]["text"] == "wechat-premium"
    assert entitlements.calls[-1] == (user_id, AI_DECISIONS_ENTITLEMENT)

    await service._handle_message(object(), account, _wechat_message("暂停通知"))
    assert center.preference_calls[-1][2] is False
    assert "已关闭" in client.sent[-1]["text"]


@pytest.mark.asyncio
async def test_ready_endpoint_never_exposes_internal_health_details(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    await health.dependency(
        "GPT",
        "ACTION_REQUIRED",
        message="provider-secret-detail",
        internal_counter=123,
    )
    app = create_app(
        factory,
        health,
        frontend_dist=tmp_path / "missing",
        auth_enabled=False,
        auth_cookie_secure=False,
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/ready")
        assert response.status_code == 503
        payload = response.json()
        assert set(payload) == {"overall", "observed_at"}
        assert payload["overall"] == "ACTION_REQUIRED"
        assert "provider-secret-detail" not in response.text
        assert "GPT" not in response.text
        assert "internal_counter" not in response.text
    finally:
        await engine.dispose()
