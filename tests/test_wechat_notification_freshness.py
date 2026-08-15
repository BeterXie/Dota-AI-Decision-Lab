from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import CanonicalMap, DurableJobRecord, MapResultRecord
from app.providers.wechat_clawbot.models import WeChatAccount
from app.providers.wechat_clawbot.service import WeChatClawBotService
from app.providers.wechat_clawbot.storage import WeChatClawBotStore
from app.snapshots.repository import SnapshotRepository


class RecordingClient:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_text(
        self,
        account: WeChatAccount,
        *,
        to_user_id: str,
        text: str,
        context_token: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        self.messages.append(text)
        return "fixture-message-id"

    async def close(self) -> None:
        return None


def _store(tmp_path: Path) -> WeChatClawBotStore:
    store = WeChatClawBotStore(tmp_path)
    store.save_account(
        WeChatAccount(
            account_id="bot-1@im.bot",
            token="token",
            base_url="https://ilinkai.weixin.qq.com",
            user_id="wechat-user-1",
            created_at=datetime.now(UTC),
        )
    )
    return store


async def _snapshot(session, *, decision_at: datetime, canonical_map_id=None):
    return await SnapshotRepository().persist(
        session,
        canonical_map_id=canonical_map_id,
        decision_at=decision_at,
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


@pytest.mark.asyncio
async def test_stale_decision_is_neither_enqueued_nor_sent(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = RecordingClient()
    service = WeChatClawBotService(
        client=client,
        store=_store(tmp_path),
        session_factory=factory,
        jobs=JobRepository(),
        max_decision_age_seconds=600,
    )
    async with factory() as session, session.begin():
        snapshot = await _snapshot(
            session,
            decision_at=datetime.now(UTC) - timedelta(seconds=601),
        )
        await service.prepare_decision_notification(session, snapshot=snapshot, decisions=[])

    async with factory() as session:
        queued = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SEND_WECHAT_DECISION.value)
        )
    assert queued == 0
    assert await service.send_decision_notification(snapshot=snapshot, decisions=[]) == 0
    assert client.messages == []

    await service.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_completed_map_decision_is_neither_enqueued_nor_sent(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = RecordingClient()
    service = WeChatClawBotService(
        client=client,
        store=_store(tmp_path),
        session_factory=factory,
        jobs=JobRepository(),
        max_decision_age_seconds=600,
    )
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        snapshot = await _snapshot(
            session,
            decision_at=now,
            canonical_map_id=canonical_map.id,
        )
        session.add(
            MapResultRecord(
                canonical_map_id=canonical_map.id,
                winner_team_id=None,
                basic_first_usable_at=now,
            )
        )
        await session.flush()
        await service.prepare_decision_notification(session, snapshot=snapshot, decisions=[])

    async with factory() as session:
        queued = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SEND_WECHAT_DECISION.value)
        )
    assert queued == 0
    assert await service.send_decision_notification(snapshot=snapshot, decisions=[]) == 0
    assert client.messages == []

    await service.stop()
    await engine.dispose()
