from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.db import Base
from app.notifications.models import NotificationBindingRecord
from app.providers.qq_bot.qr import QQUserQrBindingService
from app.providers.qq_bot.storage import QQBotStore
from app.providers.wechat_clawbot.models import WeChatQrStart, WeChatQrStatus
from app.providers.wechat_clawbot.qr import WeChatUserQrBindingService
from app.providers.wechat_clawbot.storage import WeChatClawBotStore


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            UserAccountRecord(
                id=user_id,
                email="qr@example.com",
                last_login_at=datetime.now(UTC),
            )
        )
    return engine, factory, user_id


async def _add_user(factory, email: str) -> UUID:
    user_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            UserAccountRecord(
                id=user_id,
                email=email,
                last_login_at=datetime.now(UTC),
            )
        )
    return user_id


@pytest.mark.asyncio
async def test_wechat_qr_confirmation_creates_user_owned_account_and_binding(
    tmp_path: Path,
) -> None:
    engine, factory, user_id = await _factory()

    class Client:
        def base_url(self) -> str:
            return "https://ilinkai.weixin.qq.com"

        @property
        def long_poll_timeout_seconds(self) -> float:
            return 1

        async def start_qr_login(self):
            return WeChatQrStart(qrcode="qr", qrcode_url="https://wechat.example/qr")

        async def poll_qr_status(self, *args, **kwargs):
            return WeChatQrStatus(
                status="confirmed",
                bot_token="token-user",
                account_id="bot-user@im.bot",
                user_id="owner@im.wechat",
            )

    store = WeChatClawBotStore(tmp_path / "wechat")
    service = WeChatUserQrBindingService(
        client=Client(),
        store=store,
        session_factory=factory,
    )
    started = await service.start(user_id)
    result = await service.poll(user_id, started["session_id"])

    assert result["status"] == "BOUND"
    account = store.accounts()[0]
    assert account.owner_user_id == str(user_id)
    assert account.account_mode == "USER"
    assert account.user_id == "owner@im.wechat"
    async with factory() as session:
        binding = await session.scalar(select(NotificationBindingRecord))
    assert binding is not None
    assert binding.user_id == user_id
    assert binding.destination["account_id"] == "bot-user@im.bot"
    await engine.dispose()


@pytest.mark.asyncio
async def test_qq_qr_confirmation_creates_user_owned_account_and_binding(tmp_path: Path) -> None:
    engine, factory, user_id = await _factory()

    class Bridge:
        def __init__(self):
            self.session_id = "qq-session"

        async def start_qr_binding(self):
            return {
                "session_id": self.session_id,
                "status": "WAITING",
                "qrcode_url": "https://qq.example/qr",
                "created_at": datetime.now(UTC).isoformat(),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            }

        async def poll_qr_binding(self, _session_id):
            return {
                "session_id": self.session_id,
                "status": "COMPLETED",
                "credentials": {
                    "app_id": "app-user",
                    "app_secret": "secret-user",
                    "user_openid": "openid-user",
                },
            }

        async def cancel_qr_binding(self, _session_id):
            return {"session_id": self.session_id, "status": "CANCELLED"}

    store = QQBotStore(tmp_path / "qq")
    service = QQUserQrBindingService(
        client=Bridge(),
        store=store,
        session_factory=factory,
    )
    started = await service.start(user_id)
    result = await service.poll(user_id, started["session_id"])

    assert result["status"] == "BOUND"
    account = store.accounts()[0]
    assert account.owner_user_id == str(user_id)
    assert account.user_openid == "openid-user"
    assert account.account_mode == "USER"
    async with factory() as session:
        binding = await session.scalar(select(NotificationBindingRecord))
    assert binding is not None
    assert binding.user_id == user_id
    assert binding.destination["account_id"] == "app-user"
    await engine.dispose()


@pytest.mark.asyncio
async def test_qq_qr_sessions_are_owner_scoped_and_rebinding_retires_old_account(
    tmp_path: Path,
) -> None:
    engine, factory, user_id = await _factory()
    other_user_id = await _add_user(factory, "other@example.com")

    class Bridge:
        def __init__(self):
            self.counter = 0
            self.cancelled: list[str] = []

        async def start_qr_binding(self):
            self.counter += 1
            session_id = f"qq-session-{self.counter}"
            return {
                "session_id": session_id,
                "status": "WAITING",
                "qrcode_url": f"https://qq.example/{session_id}",
                "created_at": datetime.now(UTC).isoformat(),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            }

        async def poll_qr_binding(self, session_id):
            suffix = session_id.rsplit("-", 1)[-1]
            return {
                "session_id": session_id,
                "status": "COMPLETED",
                "credentials": {
                    "app_id": f"app-user-{suffix}",
                    "app_secret": f"secret-user-{suffix}",
                    "user_openid": f"openid-user-{suffix}",
                },
            }

        async def cancel_qr_binding(self, session_id):
            self.cancelled.append(session_id)
            return {"session_id": session_id, "status": "CANCELLED"}

    bridge = Bridge()
    store = QQBotStore(tmp_path / "qq")
    service = QQUserQrBindingService(client=bridge, store=store, session_factory=factory)

    first = await service.start(user_id)
    second = await service.start(user_id)
    assert bridge.cancelled == [first["session_id"]]
    with pytest.raises(RuntimeError, match="不属于当前账号"):
        await service.poll(other_user_id, second["session_id"])
    with pytest.raises(RuntimeError, match="不存在或不属于当前账号"):
        await service.poll(user_id, first["session_id"])

    bound = await service.poll(user_id, second["session_id"])
    assert bound["status"] == "BOUND"
    assert [item.app_id for item in store.accounts()] == ["app-user-2"]
    async with factory() as session:
        bindings = list((await session.scalars(select(NotificationBindingRecord))).all())
    assert len(bindings) == 1
    assert bindings[0].status == "ACTIVE"

    third = await service.start(user_id)
    rebound = await service.poll(user_id, third["session_id"])
    assert rebound["status"] == "BOUND"
    assert [item.app_id for item in store.accounts()] == ["app-user-3"]
    async with factory() as session:
        bindings = list(
            (
                await session.scalars(
                    select(NotificationBindingRecord).order_by(NotificationBindingRecord.created_at)
                )
            ).all()
        )
    assert sorted(item.status for item in bindings) == ["ACTIVE", "DISABLED"]
    assert [item.destination["account_id"] for item in bindings if item.status == "ACTIVE"] == [
        "app-user-3"
    ]
    await engine.dispose()
