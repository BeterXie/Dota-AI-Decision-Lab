import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DurableJobRecord
from app.providers.qq_bot.bridge_client import QQBridgeClient, QQBridgeError
from app.providers.qq_bot.models import (
    QQBotAccount,
    QQBridgeEventBatch,
    QQBridgeHealth,
    QQContact,
    QQInboundMessage,
    parse_qq_target_entries,
)
from app.providers.qq_bot.service import QQBotService
from app.providers.qq_bot.storage import QQBotStore
from app.snapshots.repository import SnapshotRepository


def _account(tmp_path: Path) -> QQBotAccount:
    return QQBotAccount(
        app_id="fake-app",
        app_secret="fake-secret",
        created_at=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    )


def _contact(scope: str, target_id: str, *, subscribed: bool = True) -> QQContact:
    now = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
    return QQContact(
        scope=scope,  # type: ignore[arg-type]
        target_id=target_id,
        subscribed=subscribed,
        first_seen_at=now,
        last_seen_at=now,
    )


class RecordingBridgeClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.batches: list[QQBridgeEventBatch] = []

    async def send_text(
        self,
        *,
        scope: str,
        target_id: str,
        text: str,
        msg_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        self.sent.append(
            {
                "scope": scope,
                "target_id": target_id,
                "text": text,
                "msg_id": msg_id,
                "idempotency_key": idempotency_key,
            }
        )
        return f"message-{len(self.sent)}"

    async def events(self, cursor: int = 0) -> QQBridgeEventBatch:
        batch = QQBridgeEventBatch(events=(), cursor=cursor)
        self.batches.append(batch)
        return batch

    async def close(self) -> None:
        return None


def test_parse_qq_target_entries_accepts_c2c_and_group() -> None:
    contacts = parse_qq_target_entries(("c2c:user-1", "group:group-1"))
    assert [item.key for item in contacts] == [("c2c", "user-1"), ("group", "group-1")]
    assert all(item.subscribed for item in contacts)


def test_parse_qq_target_entries_rejects_bad_scope() -> None:
    with pytest.raises(ValueError):
        parse_qq_target_entries(("channel:user-1",))


def test_store_persists_accounts_contacts_cursor_and_preferences(tmp_path: Path) -> None:
    store = QQBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    assert store.account_count() == 1

    contact = _contact("c2c", "user-1")
    store.save_contact(contact)
    assert store.contact("c2c", "user-1") == contact
    assert [item.key for item in store.subscribed_contacts()] == [("c2c", "user-1")]

    store.set_contact_subscribed("c2c", "user-1", False)
    assert store.subscribed_contacts() == []

    store.save_cursor("fake-app", 7)
    assert store.cursor("fake-app") == 7

    store.set_decision_notifications(False)
    assert store.decision_notifications_enabled() is False

    store.remove_account("fake-app")
    assert store.account_count() == 0
    assert store.cursor("fake-app") == 0


@pytest.mark.asyncio
async def test_bridge_client_protocol() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "status": "READY",
                    "account_count": 1,
                    "gateway_connected": True,
                    "buffered_events": 2,
                },
            )
        if request.url.path == "/events":
            assert request.url.params["cursor"] == "3"
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "event_cursor": 4,
                            "scope": "group",
                            "target_id": "group-1",
                            "sender_id": "member-1",
                            "message_id": "in-4",
                            "text": "赔率",
                            "bot_mentioned": True,
                            "mentions": [],
                        }
                    ],
                    "cursor": 4,
                },
            )
        assert request.url.path == "/send"
        assert json.loads(request.content) == {
            "scope": "group",
            "target_id": "group-1",
            "text": "当前比赛赔率",
            "msg_id": "in-4",
        }
        return httpx.Response(200, json={"message_id": "out-1", "timestamp": 1})

    client = QQBridgeClient(
        base_url="http://bridge.test",
        timeout_seconds=3,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    health = await client.health()
    assert health == QQBridgeHealth(
        ok=True,
        status="READY",
        account_count=1,
        gateway_connected=True,
        buffered_events=2,
    )
    batch = await client.events(3)
    assert batch.cursor == 4
    assert batch.events[0].text == "赔率"
    message_id = await client.send_text(
        scope="group",
        target_id="group-1",
        text="当前比赛赔率",
        msg_id="in-4",
    )
    assert message_id == "out-1"
    await client.close()


@pytest.mark.asyncio
async def test_bridge_client_raises_on_error_response() -> None:
    client = QQBridgeClient(
        base_url="http://bridge.test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(503, json={"error": "gateway offline"})
            )
        ),
    )
    with pytest.raises(QQBridgeError):
        await client.send_text(scope="c2c", target_id="user-1", text="hi")
    await client.close()


@pytest.mark.asyncio
async def test_service_prepare_notification_is_idempotent(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = QQBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    store.save_contact(_contact("c2c", "user-1"))
    service = QQBotService(
        client=RecordingBridgeClient(),
        store=store,
        session_factory=factory,
        jobs=JobRepository(),
        max_decision_age_seconds=10**9,
    )
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "OG"},
                "team_b": {"id": "team-b", "name": "HULIGANI"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        decision = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="ai-view-v2",
            request_started_at=snapshot.decision_at,
            response_received_at=snapshot.decision_at,
            latency_seconds=1.0,
            raw_response={},
            normalized_response={"action": "BUY_A", "primary_reasons": ["阵容优势"]},
            parse_status="SUCCESS",
        )
        session.add(decision)
        await session.flush()
        await service.prepare_decision_notification(
            session, snapshot=snapshot, decisions=[decision]
        )
        await service.prepare_decision_notification(
            session, snapshot=snapshot, decisions=[decision]
        )

    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SEND_QQ_DECISION.value)
        )
    assert count == 1
    await service.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_sends_decision_to_configured_and_subscribed_targets(tmp_path: Path) -> None:
    store = QQBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    store.save_contact(_contact("c2c", "user-1"))
    store.save_contact(_contact("group", "group-1"))
    store.save_contact(_contact("group", "group-2", subscribed=False))
    client = RecordingBridgeClient()
    service = QQBotService(
        client=client,
        store=store,
        session_factory=None,
        jobs=JobRepository(),
        configured_targets=(_contact("group", "group-1"),),
        max_decision_age_seconds=10**9,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "OG"},
                "team_b": {"id": "team-b", "name": "HULIGANI"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        decision = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="ai-view-v2",
            request_started_at=snapshot.decision_at,
            response_received_at=snapshot.decision_at,
            latency_seconds=1.0,
            raw_response={},
            normalized_response={
                "action": "BUY_B",
                "fair_probability_a": 0.35,
                "primary_reasons": ["下路优势"],
            },
            parse_status="SUCCESS",
        )
        count = await service.send_decision_notification(snapshot=snapshot, decisions=[decision])
        assert count == 2
        assert client.sent[0]["target_id"] == "group-1"
        assert client.sent[1]["target_id"] == "user-1"
        assert "QQ" in client.sent[0]["text"]
        assert "支持 HULIGANI" in client.sent[0]["text"]
        assert "AI胜率: 65.0%" in client.sent[0]["text"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_suppresses_stale_decision(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = QQBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    store.save_contact(_contact("c2c", "user-1"))
    client = RecordingBridgeClient()
    service = QQBotService(
        client=client,
        store=store,
        session_factory=factory,
        jobs=JobRepository(),
        max_decision_age_seconds=600,
    )
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime.now(UTC) - timedelta(seconds=601),
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        await service.prepare_decision_notification(session, snapshot=snapshot, decisions=[])
        sent = await service.send_decision_notification(snapshot=snapshot, decisions=[])

    async with factory() as session:
        queued = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SEND_QQ_DECISION.value)
        )
    assert queued == 0
    assert sent == 0
    assert client.sent == []
    await service.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_inbound_subscribes_and_replies(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = QQBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    client = RecordingBridgeClient()
    service = QQBotService(
        client=client,
        store=store,
        session_factory=factory,
        jobs=JobRepository(),
        group_require_mention=True,
    )
    async with factory() as session, session.begin():
        await service._handle_message(
            session,
            QQInboundMessage(
                event_cursor=1,
                scope="c2c",
                target_id="user-1",
                sender_id="user-1",
                message_id="in-1",
                text="比赛",
            ),
        )
        await service._handle_message(
            session,
            QQInboundMessage(
                event_cursor=2,
                scope="group",
                target_id="group-1",
                sender_id="member-1",
                message_id="in-2",
                text="订阅通知",
                bot_mentioned=True,
            ),
        )

    assert store.contact("c2c", "user-1").subscribed is True
    assert store.contact("group", "group-1").subscribed is True
    assert client.sent[0]["msg_id"] == "in-1"
    assert client.sent[0]["text"] == "当前没有正在追踪的比赛。"
    assert "已订阅" in client.sent[1]["text"]
    await service.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_ignores_unmentioned_group_message_when_required(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = QQBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    client = RecordingBridgeClient()
    service = QQBotService(
        client=client,
        store=store,
        session_factory=factory,
        jobs=JobRepository(),
        group_require_mention=True,
    )
    async with factory() as session, session.begin():
        await service._handle_message(
            session,
            QQInboundMessage(
                event_cursor=1,
                scope="group",
                target_id="group-1",
                sender_id="member-1",
                message_id="in-1",
                text="比赛",
                bot_mentioned=False,
            ),
        )
    assert client.sent == []
    assert store.contact("group", "group-1") is None
    await service.stop()
    await engine.dispose()
