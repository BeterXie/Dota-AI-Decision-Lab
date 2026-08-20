from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.jobs.handlers import ApplicationJobHandlers
from app.models import AiDecisionRecord
from app.snapshots.repository import SnapshotRepository


class RecordingNotificationService:
    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str | None]]] = []

    async def prepare(self, _session, *, snapshot, decisions) -> None:
        self.batches.append(
            [
                (
                    decision.provider,
                    decision.normalized_response.get("action")
                    if isinstance(decision.normalized_response, dict)
                    else None,
                )
                for decision in decisions
            ]
        )


class RecordingQQService:
    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str | None]]] = []

    async def prepare_decision_notification(self, _session, *, snapshot, decisions) -> None:
        self.batches.append(
            [
                (
                    decision.provider,
                    decision.normalized_response.get("action")
                    if isinstance(decision.normalized_response, dict)
                    else None,
                )
                for decision in decisions
            ]
        )


class RecordingWeChatService:
    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str | None]]] = []

    async def prepare_decision_notification(self, _session, *, snapshot, decisions) -> None:
        self.batches.append(
            [
                (
                    decision.provider,
                    decision.normalized_response.get("action")
                    if isinstance(decision.normalized_response, dict)
                    else None,
                )
                for decision in decisions
            ]
        )


@pytest.mark.asyncio
async def test_buy_trigger_notifies_with_complete_current_multi_ai_batch() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email = RecordingNotificationService()
    wechat = RecordingWeChatService()
    qq_bot = RecordingQQService()
    snapshots = SnapshotRepository()
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        buy = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="view-v1",
            request_started_at=now,
            response_received_at=now + timedelta(seconds=2),
            latency_seconds=2.0,
            parse_status="SUCCESS",
            normalized_response={"action": "BUY_A"},
        )
        no_buy = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="anthropic",
            model="claude-test",
            model_version="claude-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="view-v1",
            request_started_at=now,
            response_received_at=now + timedelta(seconds=3),
            latency_seconds=3.0,
            parse_status="SUCCESS",
            normalized_response={"action": "NO_BUY"},
        )
        failed = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="gemini",
            model="gemini-test",
            model_version="gemini-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="view-v1",
            request_started_at=now,
            response_received_at=now + timedelta(seconds=4),
            latency_seconds=4.0,
            parse_status="TIMEOUT",
            error="fixture timeout",
        )

        handler = ApplicationJobHandlers(
            SimpleNamespace(
                settings=SimpleNamespace(ai_notification_max_latency_seconds=50.0),
                email_notifications=email,
                wechat_clawbot=wechat,
                qq_bot=qq_bot,
            )
        )
        await handler._prepare_decision_notifications(
            session,
            snapshot,
            [buy, no_buy, failed],
        )

    expected = [
        ("openai", "BUY_A"),
        ("anthropic", "NO_BUY"),
        ("gemini", None),
    ]
    assert email.batches == [expected]
    assert wechat.batches == [expected]
    assert qq_bot.batches == [expected]
    await engine.dispose()


@pytest.mark.asyncio
async def test_late_decisions_are_stored_but_excluded_from_notifications() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email = RecordingNotificationService()
    wechat = RecordingWeChatService()
    qq_bot = RecordingQQService()
    snapshots = SnapshotRepository()
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        late_buy = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="deepseek",
            model="deepseek-test",
            model_version="deepseek-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="view-v1",
            request_started_at=now,
            response_received_at=now + timedelta(seconds=60),
            latency_seconds=60.0,
            parse_status="SUCCESS",
            normalized_response={"action": "BUY_B"},
        )
        session.add(late_buy)
        await session.flush()

        handler = ApplicationJobHandlers(
            SimpleNamespace(
                settings=SimpleNamespace(ai_notification_max_latency_seconds=50.0),
                email_notifications=email,
                wechat_clawbot=wechat,
                qq_bot=qq_bot,
            )
        )
        await handler._prepare_decision_notifications(session, snapshot, [late_buy])

    assert email.batches == []
    assert wechat.batches == []
    assert qq_bot.batches == []
    async with factory() as session:
        assert await session.get(AiDecisionRecord, late_buy.id) is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_late_prior_buy_does_not_suppress_a_timely_notification() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email = RecordingNotificationService()
    wechat = RecordingWeChatService()
    qq_bot = RecordingQQService()
    snapshots = SnapshotRepository()
    canonical_map_id = uuid4()
    now = datetime(2026, 8, 15, 12, 5, tzinfo=UTC)

    async with factory() as session, session.begin():
        prior_snapshot = await snapshots.persist(
            session,
            canonical_map_id=canonical_map_id,
            decision_at=now - timedelta(minutes=5),
            mode="LIVE_BASIC",
            identity={"team_a": {"id": "team-a"}, "team_b": {"id": "team-b"}},
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        current_snapshot = await snapshots.persist(
            session,
            canonical_map_id=canonical_map_id,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={"team_a": {"id": "team-a"}, "team_b": {"id": "team-b"}},
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 900},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        late_prior = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=prior_snapshot.snapshot_id,
            snapshot_hash=prior_snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="view-v1",
            request_started_at=now - timedelta(minutes=5),
            response_received_at=now - timedelta(minutes=4),
            latency_seconds=60.0,
            parse_status="SUCCESS",
            normalized_response={"action": "BUY_A"},
        )
        timely_current = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=current_snapshot.snapshot_id,
            snapshot_hash=current_snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="view-v1",
            request_started_at=now,
            response_received_at=now + timedelta(seconds=20),
            latency_seconds=20.0,
            parse_status="SUCCESS",
            normalized_response={"action": "BUY_A"},
        )
        session.add_all([late_prior, timely_current])
        await session.flush()

        handler = ApplicationJobHandlers(
            SimpleNamespace(
                settings=SimpleNamespace(ai_notification_max_latency_seconds=50.0),
                email_notifications=email,
                wechat_clawbot=wechat,
                qq_bot=qq_bot,
            )
        )
        await handler._prepare_decision_notifications(
            session,
            current_snapshot,
            [timely_current],
        )

    expected = [[("openai", "BUY_A")]]
    assert email.batches == expected
    assert wechat.batches == expected
    assert qq_bot.batches == expected
    await engine.dispose()
