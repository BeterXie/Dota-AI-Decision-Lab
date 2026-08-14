from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (
    CanonicalHero,
    CanonicalMap,
    CanonicalPlayer,
    DraftSlotRecord,
    DraftSnapshotRecord,
    HistoricalMapRecord,
    HistoricalPlayerMapRecord,
)
from app.runtime.health import HealthRegistry
from app.web import create_app


@pytest.mark.asyncio
async def test_draft_hero_recent_uses_latest_ten_before_statistics_cutoff() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = datetime(2026, 8, 1, tzinfo=UTC)
    cutoff = base + timedelta(days=11)

    async with factory.begin() as session:
        player = CanonicalPlayer(account_id=1001, name="watson")
        hero = CanonicalHero(hero_id=36, name="Necrophos")
        canonical_map = CanonicalMap(map_number=1, valve_match_id=900001)
        session.add_all((player, hero, canonical_map))
        await session.flush()

        draft = DraftSnapshotRecord(
            canonical_map_id=canonical_map.id,
            valve_match_id=900001,
            complete=True,
            blockers=[],
            warnings=[],
            payload_hash="draft-recent-fixture",
            statistics_cutoff=cutoff,
            observed_at=cutoff,
            raw_event_id=uuid4(),
        )
        session.add(draft)
        await session.flush()
        session.add(
            DraftSlotRecord(
                draft_snapshot_id=draft.id,
                side="radiant",
                position=1,
                account_id=player.account_id,
                canonical_player_id=player.id,
                hero_id=hero.hero_id,
                source="DLTV",
                confidence=1.0,
            )
        )

        # Eleven eligible historical uses: the oldest is intentionally excluded
        # by the 10-game window. Among the latest ten, seven are wins and three losses.
        for index in range(11):
            usable_at = base + timedelta(days=index, hours=1)
            fact = HistoricalMapRecord(
                provider="stratz",
                provider_match_id=f"hist-{index}",
                started_at=base + timedelta(days=index),
                first_usable_at=usable_at,
                sync_status="BASIC_READY",
                raw_event_id=uuid4(),
            )
            session.add(fact)
            await session.flush()
            session.add(
                HistoricalPlayerMapRecord(
                    historical_map_id=fact.id,
                    canonical_player_id=player.id,
                    account_id=player.account_id,
                    hero_id=hero.hero_id,
                    position=1,
                    won=1 <= index <= 7,
                    basic_first_usable_at=usable_at,
                )
            )

        # A later use must not leak into the draft-time statistic.
        future_usable_at = cutoff + timedelta(days=1, hours=1)
        future_fact = HistoricalMapRecord(
            provider="stratz",
            provider_match_id="future-use",
            started_at=cutoff + timedelta(days=1),
            first_usable_at=future_usable_at,
            sync_status="BASIC_READY",
            raw_event_id=uuid4(),
        )
        session.add(future_fact)
        await session.flush()
        session.add(
            HistoricalPlayerMapRecord(
                historical_map_id=future_fact.id,
                canonical_player_id=player.id,
                account_id=player.account_id,
                hero_id=hero.hero_id,
                position=1,
                won=True,
                basic_first_usable_at=future_usable_at,
            )
        )

    app = create_app(factory, HealthRegistry())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/maps/{canonical_map.id}/draft-hero-recent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window"] == 10
    assert len(payload["slots"]) == 1
    recent = payload["slots"][0]["recent"]
    assert recent["maps"] == 10
    assert recent["wins"] == 7
    assert recent["losses"] == 3
    assert recent["win_rate"] == pytest.approx(0.7)
    assert recent["last_included_match_id"] == "hist-10"

    await engine.dispose()
