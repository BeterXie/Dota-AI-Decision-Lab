from datetime import UTC, datetime
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
            parse_status="TIMEOUT",
            error="fixture timeout",
        )

        handler = ApplicationJobHandlers(
            SimpleNamespace(
                email_notifications=email,
                wechat_clawbot=wechat,
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
    await engine.dispose()
