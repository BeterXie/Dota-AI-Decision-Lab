from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.notifications.center import DeliveryTarget
from app.providers.qq_bot import user_service as qq_user_service
from app.providers.wechat_clawbot import user_service as wechat_user_service


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _DeliveryCenter:
    def __init__(self, targets: dict[UUID, DeliveryTarget]) -> None:
        self.targets = targets
        self.failed: list[UUID] = []
        self.sent: list[UUID] = []
        self.expired: list[UUID] = []

    async def batch_delivery_ids(self, **kwargs) -> list[UUID]:
        return list(self.targets)

    async def start_delivery(self, delivery_id: UUID) -> DeliveryTarget | None:
        return self.targets[delivery_id]

    async def mark_failed(self, delivery_id: UUID, exc: Exception) -> None:
        self.failed.append(delivery_id)

    async def mark_sent(self, delivery_id: UUID, provider_message_id: str | None) -> None:
        self.sent.append(delivery_id)

    async def mark_expired(self, delivery_id: UUID, reason: str) -> None:
        self.expired.append(delivery_id)


def _target(channel: str, destination: dict[str, str]) -> DeliveryTarget:
    return DeliveryTarget(
        delivery_id=uuid4(),
        user_id=uuid4(),
        binding_id=uuid4(),
        channel=channel,
        destination=destination,
        label=None,
        idempotency_key=f"test/{uuid4()}",
        snapshot_id=uuid4(),
        decision_ids=(uuid4(),),
        decision_batch_key="batch",
    )


async def _allow_notification(*args, **kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_qq_failed_recipient_does_not_block_later_recipient(monkeypatch) -> None:
    attempted: list[str] = []

    class Client:
        async def send_text(self, *, target_id: str, **kwargs) -> str:
            attempted.append(target_id)
            if target_id == "bad-user":
                raise RuntimeError("simulated QQ failure")
            return "qq-message"

    bad = _target("QQ", {"scope": "c2c", "target_id": "bad-user"})
    good = _target("QQ", {"scope": "c2c", "target_id": "good-user"})
    center = _DeliveryCenter({bad.delivery_id: bad, good.delivery_id: good})
    service = qq_user_service.UserScopedQQBotService(
        client=Client(),
        store=object(),
        session_factory=_SessionFactory(),
        jobs=object(),
        max_decision_age_seconds=10**9,
    )
    service._notification_center = center
    monkeypatch.setattr(service, "_decision_notification_block_reason", _allow_notification)
    monkeypatch.setattr(qq_user_service, "render_decision_notification", lambda *args, **kwargs: "BUY")
    snapshot = SimpleNamespace(snapshot_id=uuid4(), decision_at=datetime.now(UTC))
    decisions = [SimpleNamespace(id=uuid4())]

    with pytest.raises(RuntimeError, match="1 QQ notification delivery target"):
        await service.send_decision_notification(snapshot=snapshot, decisions=decisions)

    assert attempted == ["bad-user", "good-user"]
    assert center.failed == [bad.delivery_id]
    assert center.sent == [good.delivery_id]


@pytest.mark.asyncio
async def test_wechat_failed_recipient_does_not_block_later_recipient(monkeypatch) -> None:
    attempted: list[str] = []

    class Client:
        async def send_text(self, account, *, to_user_id: str, **kwargs) -> str:
            attempted.append(to_user_id)
            if to_user_id == "bad-user":
                raise RuntimeError("simulated WeChat failure")
            return "wechat-message"

    account = SimpleNamespace(account_id="bot-account", context_token="context")
    store = SimpleNamespace(accounts=lambda: [account])
    bad = _target("WECHAT", {"account_id": "bot-account", "user_id": "bad-user"})
    good = _target("WECHAT", {"account_id": "bot-account", "user_id": "good-user"})
    center = _DeliveryCenter({bad.delivery_id: bad, good.delivery_id: good})
    service = wechat_user_service.UserScopedWeChatClawBotService(
        client=Client(),
        store=store,
        session_factory=_SessionFactory(),
        jobs=object(),
        max_decision_age_seconds=10**9,
    )
    service._notification_center = center
    monkeypatch.setattr(service, "_decision_notification_block_reason", _allow_notification)
    monkeypatch.setattr(
        wechat_user_service,
        "render_decision_notification",
        lambda *args, **kwargs: "BUY",
    )
    snapshot = SimpleNamespace(snapshot_id=uuid4(), decision_at=datetime.now(UTC))
    decisions = [SimpleNamespace(id=uuid4())]

    with pytest.raises(RuntimeError, match="1 WeChat notification delivery target"):
        await service.send_decision_notification(snapshot=snapshot, decisions=decisions)

    assert attempted == ["bad-user", "good-user"]
    assert center.failed == [bad.delivery_id]
    assert center.sent == [good.delivery_id]
