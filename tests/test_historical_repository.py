import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.history.repository import HistoricalRepository
from app.models import CanonicalTeam, HistoricalMapRecord, ProviderTeamMapping
from app.providers.opendota.normalizer import normalize_match as normalize_opendota
from app.providers.stratz.history_queries import normalize_match as normalize_stratz

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_provider_result_conflict_is_explicit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    fetched_at = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        radiant = CanonicalTeam(name="Radiant")
        dire = CanonicalTeam(name="Dire")
        session.add_all([radiant, dire])
        await session.flush()
        for provider in ("opendota", "stratz"):
            session.add_all(
                [
                    ProviderTeamMapping(
                        provider=provider,
                        provider_team_id="100",
                        canonical_team_id=radiant.id,
                    ),
                    ProviderTeamMapping(
                        provider=provider,
                        provider_team_id="200",
                        canonical_team_id=dire.id,
                    ),
                ]
            )
        opendota_payload = json.loads(
            (FIXTURES / "opendota_match.json").read_text(encoding="utf-8")
        )
        stratz_payload = json.loads((FIXTURES / "stratz_match.json").read_text(encoding="utf-8"))
        stratz_payload["data"]["match"]["didRadiantWin"] = False
        repository = HistoricalRepository()
        first = await repository.persist_bundle(
            session,
            normalize_opendota(opendota_payload, fetched_at=fetched_at),
            raw_event_id=uuid4(),
            normalizer_version="opendota-match-v1",
        )
        second = await repository.persist_bundle(
            session,
            normalize_stratz(stratz_payload, fetched_at=fetched_at + timedelta(seconds=1)),
            raw_event_id=uuid4(),
            normalizer_version="stratz-match-v1",
        )
        await session.flush()

        assert first.sync_status == "DATA_CONFLICT"
        assert second.sync_status == "DATA_CONFLICT"
        facts = list((await session.scalars(select(HistoricalMapRecord))).all())
        assert {fact.provider for fact in facts} == {"opendota", "stratz"}
        assert len({fact.canonical_map_id for fact in facts}) == 1

    await engine.dispose()
