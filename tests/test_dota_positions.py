import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.draft.coordinator import DltvBootstrapCoordinator
from app.draft.role_assignment import DraftRoleAssignmentService, _resolve_side_from_history
from app.events.outbox import EventRepository
from app.identity.resolver import IdentityResolver
from app.models import DomainEventRecord, DraftSlotRecord, DraftSnapshotRecord, ProviderRawEvent
from app.providers.common import TimedPayload
from app.providers.dltv.draft_picks import DltvProviderPick
from app.repositories.raw import RawEventRepository


class _DotaPositionClient:
    def __init__(self, received_at: datetime) -> None:
        self.received_at = received_at

    async def execute(self, *, operation_name: str, query: str, variables: dict) -> TimedPayload:
        players = []
        for radiant, account_start, hero_start in ((True, 1000, 10), (False, 2000, 20)):
            for provider_slot in range(1, 6):
                players.append(
                    {
                        "steamAccountId": account_start + provider_slot,
                        "heroId": hero_start + provider_slot,
                        "position": f"POSITION_{6 - provider_slot}",
                        "isRadiant": radiant,
                    }
                )
        return TimedPayload(
            payload={"data": {"match": {"id": variables["matchId"], "players": players}}},
            request_started_at=self.received_at - timedelta(milliseconds=100),
            received_at=self.received_at,
        )


def _picks() -> tuple[DltvProviderPick, ...]:
    rows = []
    for side, account_start, hero_start in (("radiant", 1000, 10), ("dire", 2000, 20)):
        for provider_slot in range(1, 6):
            rows.append(
                DltvProviderPick(
                    side=side,
                    provider_slot=provider_slot,
                    account_id=account_start + provider_slot,
                    hero_id=hero_start + provider_slot,
                )
            )
    return tuple(rows)


@pytest.mark.asyncio
async def test_explicit_dota_positions_override_provider_ordering() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    service = DraftRoleAssignmentService(
        stratz=_DotaPositionClient(observed_at + timedelta(seconds=1)),
        raw_events=RawEventRepository(),
    )
    async with factory() as session, session.begin():
        result = await service.resolve(
            session, valve_match_id=42, picks=_picks(), observed_at=observed_at
        )
    by_account = {slot.account_id: slot for slot in result.draft.slots}
    assert result.draft.complete is True
    assert by_account[1001].position == 5
    assert by_account[1005].position == 1
    assert by_account[1001].position != 1
    assert all(slot.source == "STRATZ_CURRENT_MATCH" for slot in result.draft.slots)
    await engine.dispose()


def test_historical_position_resolver_accepts_four_map_evidence() -> None:
    base = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    picks = tuple(
        DltvProviderPick(
            side="radiant",
            provider_slot=position,
            account_id=1000 + position,
            hero_id=10 + position,
        )
        for position in range(1, 6)
    )
    evidence = {
        pick.account_id: [(position, base - timedelta(days=index)) for index in range(5)]
        for position, pick in enumerate(picks, start=1)
    }
    # Topson-style sparse roster member: only 4 distinct positioned maps.
    evidence[1005] = [(5, base - timedelta(days=index)) for index in range(4)]

    resolved = _resolve_side_from_history(picks, evidence)

    assert resolved is not None
    slots, _cutoff = resolved
    assert [slot.position for slot in sorted(slots, key=lambda slot: slot.account_id)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert slots[4].confidence < slots[0].confidence


def test_historical_position_resolver_rejects_three_map_evidence() -> None:
    base = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    picks = tuple(
        DltvProviderPick(
            side="radiant",
            provider_slot=position,
            account_id=1000 + position,
            hero_id=10 + position,
        )
        for position in range(1, 6)
    )
    evidence = {
        pick.account_id: [(position, base - timedelta(days=index)) for index in range(5)]
        for position, pick in enumerate(picks, start=1)
    }
    evidence[1005] = [(5, base - timedelta(days=index)) for index in range(3)]

    assert _resolve_side_from_history(picks, evidence) is None


class _FixtureStratzClient:
    def __init__(self, received_at: datetime) -> None:
        self.received_at = received_at

    async def execute(self, *, operation_name: str, query: str, variables: dict) -> TimedPayload:
        players = []
        for is_radiant, account_start, hero_start in ((True, 1000, 1), (False, 2000, 101)):
            for provider_slot in range(1, 6):
                players.append(
                    {
                        "steamAccountId": account_start + provider_slot,
                        "heroId": hero_start + provider_slot - 1,
                        "position": f"POSITION_{6 - provider_slot}",
                        "isRadiant": is_radiant,
                    }
                )
        return TimedPayload(
            payload={"data": {"match": {"id": variables["matchId"], "players": players}}},
            request_started_at=self.received_at - timedelta(milliseconds=100),
            received_at=self.received_at,
        )


class _UnusedBootstrapClient:
    async def get_live(self, valve_match_id: int) -> TimedPayload:
        raise AssertionError("rebuild must not call the live DLTV endpoint")


class _FixtureBootstrapClient:
    def __init__(self, payload: dict, received_at: datetime) -> None:
        self.payload = payload
        self.received_at = received_at

    async def get_live(self, valve_match_id: int) -> TimedPayload:
        return TimedPayload(
            payload=self.payload,
            request_started_at=self.received_at - timedelta(milliseconds=100),
            received_at=self.received_at,
        )


@pytest.mark.asyncio
async def test_bootstrap_positive_game_time_emits_one_map_started_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    received_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    valve_match_id = 8940730389
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "dltv_bootstrap.json").read_text(
            encoding="utf-8"
        )
    )
    raw_events = RawEventRepository()
    coordinator = DltvBootstrapCoordinator(
        client=_FixtureBootstrapClient(payload, received_at),
        raw_events=raw_events,
        events=EventRepository(),
        identities=IdentityResolver(),
        role_assignment=DraftRoleAssignmentService(
            stratz=_FixtureStratzClient(received_at + timedelta(seconds=1)),
            raw_events=raw_events,
        ),
    )

    async with factory() as session, session.begin():
        first = await coordinator.bootstrap(session, valve_match_id=valve_match_id)
    ended_at = received_at + timedelta(minutes=45)
    async with factory() as session, session.begin():
        second = await coordinator.bootstrap(
            session,
            valve_match_id=valve_match_id,
            ended_at=ended_at,
        )

    async with factory() as session:
        started_events = list(
            (
                await session.scalars(
                    select(DomainEventRecord).where(
                        DomainEventRecord.event_type == "MAP_STARTED"
                    )
                )
            ).all()
        )
        ended_events = list(
            (
                await session.scalars(
                    select(DomainEventRecord).where(
                        DomainEventRecord.event_type == "MAP_ENDED"
                    )
                )
            ).all()
        )

    assert second.resolved.canonical_map_id == first.resolved.canonical_map_id
    assert len(started_events) == 1
    assert started_events[0].aggregate_id == str(first.resolved.canonical_map_id)
    assert started_events[0].occurred_at == received_at.replace(tzinfo=None)
    assert len(ended_events) == 1
    assert ended_events[0].aggregate_id == str(first.resolved.canonical_map_id)
    assert ended_events[0].occurred_at == ended_at.replace(tzinfo=None)
    await engine.dispose()


async def _rebuild_fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    received_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    valve_match_id = 8940730389
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "dltv_bootstrap.json").read_text(encoding="utf-8")
    )
    raw_events = RawEventRepository()
    async with factory() as session, session.begin():
        session.add(
            ProviderRawEvent(
                provider="dltv",
                event_type="DLTV_BOOTSTRAP",
                provider_key=str(valve_match_id),
                request_started_at=received_at - timedelta(milliseconds=100),
                received_at=received_at,
                payload=payload,
                payload_hash="fixture-hash",
                parser_version="test",
            )
        )
        await session.flush()
        stored_event_id = await session.scalar(
            select(ProviderRawEvent.id).where(ProviderRawEvent.provider_key == str(valve_match_id))
        )
    coordinator = DltvBootstrapCoordinator(
        client=_UnusedBootstrapClient(),
        raw_events=raw_events,
        events=EventRepository(),
        identities=IdentityResolver(),
        role_assignment=DraftRoleAssignmentService(
            stratz=_FixtureStratzClient(received_at + timedelta(seconds=1)),
            raw_events=raw_events,
        ),
    )
    return engine, factory, coordinator, valve_match_id, payload, stored_event_id


@pytest.mark.asyncio
async def test_rebuild_legacy_draft_from_stored_payload_appends_verified_positions() -> None:
    (
        engine,
        factory,
        coordinator,
        valve_match_id,
        payload,
        stored_event_id,
    ) = await _rebuild_fixture()
    async with factory() as session, session.begin():
        result = await coordinator.rebuild_draft_from_stored_payload(
            session,
            valve_match_id=valve_match_id,
            payload=payload,
            raw_event_id=stored_event_id,
        )

    async with factory() as session:
        snapshots = list(
            (
                await session.scalars(
                    select(DraftSnapshotRecord).where(
                        DraftSnapshotRecord.valve_match_id == valve_match_id
                    )
                )
            ).all()
        )
        slots = list(
            (
                await session.scalars(
                    select(DraftSlotRecord)
                    .join(
                        DraftSnapshotRecord,
                        DraftSnapshotRecord.id == DraftSlotRecord.draft_snapshot_id,
                    )
                    .where(DraftSnapshotRecord.valve_match_id == valve_match_id)
                )
            ).all()
        )

    assert result.appended is True
    assert result.draft.complete is True
    assert len(snapshots) == 1
    assert snapshots[0].raw_event_id == stored_event_id
    assert snapshots[0].observed_at.replace(tzinfo=UTC) >= datetime.now(UTC) - timedelta(seconds=10)
    assert len(slots) == 10
    assert all(slot.source == "STRATZ_CURRENT_MATCH" for slot in slots)
    by_account = {slot.account_id: slot for slot in slots}
    assert by_account[1001].position == 5
    assert by_account[1005].position == 1
    assert by_account[2001].position == 5
    assert by_account[2005].position == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_rebuild_appends_fresh_row_when_latest_is_still_legacy() -> None:
    (
        engine,
        factory,
        coordinator,
        valve_match_id,
        payload,
        stored_event_id,
    ) = await _rebuild_fixture()
    async with factory() as session, session.begin():
        first = await coordinator.rebuild_draft_from_stored_payload(
            session,
            valve_match_id=valve_match_id,
            payload=payload,
            raw_event_id=stored_event_id,
        )
    assert first.appended is True

    # Simulate the pre-fix corner: the verified repair row carries an old
    # timestamp and a legacy row with the same payload sits slightly newer,
    # so the legacy snapshot is still the "latest" draft.
    old = datetime(2026, 8, 12, 11, 0, tzinfo=UTC).replace(tzinfo=None)
    async with factory() as session, session.begin():
        verified = (
            await session.execute(
                select(DraftSnapshotRecord).where(
                    DraftSnapshotRecord.valve_match_id == valve_match_id
                )
            )
        ).scalar_one()
        verified.observed_at = old
        verified.statistics_cutoff = old
        legacy = DraftSnapshotRecord(
            canonical_map_id=verified.canonical_map_id,
            valve_match_id=valve_match_id,
            complete=True,
            blockers=[],
            warnings=[],
            payload_hash="legacy-provider-ordering",
            statistics_cutoff=old + timedelta(seconds=1),
            observed_at=old + timedelta(seconds=1),
            raw_event_id=stored_event_id,
        )
        session.add(legacy)
        await session.flush()
        session.add(
            DraftSlotRecord(
                draft_snapshot_id=legacy.id,
                side="radiant",
                position=1,
                account_id=None,
                hero_id=None,
                source="DLTV_SLOT",
                confidence=1.0,
            )
        )

    async with factory() as session, session.begin():
        second = await coordinator.rebuild_draft_from_stored_payload(
            session,
            valve_match_id=valve_match_id,
            payload=payload,
            raw_event_id=stored_event_id,
        )

    async with factory() as session:
        latest = (
            await session.execute(
                select(DraftSnapshotRecord)
                .where(DraftSnapshotRecord.valve_match_id == valve_match_id)
                .order_by(DraftSnapshotRecord.observed_at.desc())
                .limit(1)
            )
        ).scalar_one()
        latest_legacy_slots = bool(
            await session.scalar(
                select(DraftSlotRecord.id)
                .where(
                    DraftSlotRecord.draft_snapshot_id == latest.id,
                    DraftSlotRecord.source == "DLTV_SLOT",
                )
                .limit(1)
            )
        )

    assert second.appended is True
    assert latest.id != legacy.id
    assert latest_legacy_slots is False
    assert latest.observed_at.replace(tzinfo=UTC) >= datetime.now(UTC) - timedelta(seconds=10)
    await engine.dispose()
