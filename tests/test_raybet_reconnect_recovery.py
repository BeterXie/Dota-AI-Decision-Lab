import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.jobs.repository import JobRepository
from app.market.registry_recovery import enqueue_recent_raybet_registry_refreshes
from app.models import (
    CanonicalSeries,
    CanonicalTeam,
    DurableJobRecord,
    ProviderMatchMapping,
)
from app.providers.raybet.socket import RayBetSocketClient


class _StalledConnection:
    def __init__(self) -> None:
        self._responses = [json.dumps({"rid": 1}), json.dumps({"rid": 2}), "#1"]
        self.sent: list[str] = []

    async def send(self, value: str) -> None:
        self.sent.append(value)

    async def recv(self) -> str:
        if self._responses:
            return self._responses.pop(0)
        await asyncio.Future()
        raise AssertionError("unreachable")


class _ConnectContext:
    def __init__(self, connection: _StalledConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _StalledConnection:
        return self._connection

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.mark.asyncio
async def test_raybet_socket_reconnects_when_business_messages_stop(monkeypatch) -> None:
    connection = _StalledConnection()

    def fake_connect(_self):
        return _ConnectContext(connection)

    monkeypatch.setattr(RayBetSocketClient, "_connect", fake_connect)
    client = RayBetSocketClient(
        "wss://recorded.invalid",
        "https://recorded.invalid",
        business_message_timeout_seconds=0.02,
    )
    states: list[tuple[str, str | None]] = []

    async def on_publish(_message: dict) -> None:
        raise AssertionError("stalled connection must not publish")

    async def on_state(state: str, error: str | None) -> None:
        states.append((state, error))
        if state == "DISCONNECTED":
            await client.stop()

    await client.run(on_publish, on_state)

    assert [state for state, _error in states] == [
        "CONNECTING",
        "CONNECTED",
        "DISCONNECTED",
    ]
    assert "no business message" in (states[-1][1] or "")
    assert "#2" in connection.sent


@pytest.mark.asyncio
async def test_socket_connection_enqueues_recent_mapped_market_bootstrap() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    connected_at = datetime(2026, 8, 21, 3, 30, 45, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        current = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            scheduled_at=connected_at - timedelta(hours=1),
        )
        old = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            scheduled_at=connected_at - timedelta(hours=13),
        )
        session.add_all((current, old))
        await session.flush()
        session.add_all(
            (
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id="38428967",
                    canonical_series_id=current.id,
                    resolved_by="TEST",
                    confidence=1.0,
                ),
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id="38428968",
                    canonical_series_id=old.id,
                    resolved_by="TEST",
                    confidence=1.0,
                ),
            )
        )

    jobs = JobRepository()
    for _attempt in range(2):
        async with factory() as session, session.begin():
            assert (
                await enqueue_recent_raybet_registry_refreshes(
                    session,
                    jobs=jobs,
                    connected_at=connected_at,
                )
                == 1
            )

    async with factory() as session:
        records = list((await session.scalars(select(DurableJobRecord))).all())

    assert len(records) == 1
    assert records[0].job_type == "REFRESH_ODDS_REGISTRY"
    assert records[0].dedupe_key == "raybet-socket-recovery:38428967:202608210330"
    assert records[0].payload == {
        "provider_match_id": 38428967,
        "trigger": "RAYBET_SOCKET_CONNECTED",
    }
    assert records[0].priority == 50
    await engine.dispose()
