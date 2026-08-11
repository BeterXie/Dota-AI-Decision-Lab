import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.providers.dltv.parser import (
    delayed_detail_is_fresh,
    parse_bootstrap_identity,
    parse_draft,
    parse_fast_state,
)
from app.providers.dltv.reducer import DltvStateReducer
from app.providers.dltv.socket import DltvSocketClient
from app.runtime.health import HealthRegistry
from app.runtime.supervisor import Supervisor
from app.runtime.worker import ServiceWorker

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture() -> dict:
    return json.loads((FIXTURES / "dltv_bootstrap.json").read_text(encoding="utf-8"))


def test_recorded_bootstrap_resolves_identity_and_ten_draft_slots() -> None:
    payload = _fixture()
    identity = parse_bootstrap_identity(payload, valve_match_id=8940730389)
    draft = parse_draft(payload)

    assert identity.series_id == 427609
    assert identity.map_number == 2
    assert draft.complete is True
    assert len(draft.slots) == 10
    for side in ("radiant", "dire"):
        assert {slot.position for slot in draft.slots if slot.side == side} == set(range(1, 6))


def test_fast_state_deduplicates_and_delayed_detail_is_rejected() -> None:
    payload = _fixture()
    received_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    first = parse_fast_state(payload, valve_match_id=8940730389, received_at=received_at)
    duplicate = parse_fast_state(payload, valve_match_id=8940730389, received_at=received_at)
    reducer = DltvStateReducer()

    assert first.game_time_seconds == 1061
    assert first.radiant_nw_lead == -6643
    assert reducer.changed(first) is True
    assert reducer.changed(duplicate) is False
    assert delayed_detail_is_fresh(payload, max_delay_seconds=30) is False


class _FakeSocketIo:
    def __init__(self) -> None:
        self.connected = False
        self.connect_attempts = 0
        self.handlers: dict[str, object] = {}
        self._wait = asyncio.Event()

    def event(self, function):
        self.handlers[function.__name__] = function
        return function

    def on(self, event_name: str):
        def register(function):
            self.handlers[event_name] = function
            return function

        return register

    async def connect(self, *_args, **_kwargs) -> None:
        self.connect_attempts += 1
        if self.connect_attempts == 1:
            raise ConnectionError("recorded 502")
        self.connected = True
        await self.handlers["connect"]()

    async def wait(self) -> None:
        await self._wait.wait()

    async def disconnect(self) -> None:
        self.connected = False
        self._wait.set()


@pytest.mark.asyncio
async def test_dltv_socket_is_restarted_after_connect_failure() -> None:
    client = DltvSocketClient("https://recorded.invalid")
    fake_socket = _FakeSocketIo()
    client._sio = fake_socket
    health = HealthRegistry()
    connected = asyncio.Event()

    async def on_event(_event: str, _payload: dict) -> None:
        return None

    async def on_state(state: str, _error: str | None) -> None:
        if state == "CONNECTED":
            connected.set()

    worker = ServiceWorker(
        name="DltvSocketWorker",
        run=lambda: client.run(on_event, on_state),
        stop=client.stop,
        health_registry=health,
    )
    supervisor = Supervisor([worker], health=health, max_backoff_seconds=0.01)
    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(connected.wait(), timeout=1)
    await supervisor.stop()
    await task

    snapshot = await health.worker("DltvSocketWorker")
    assert fake_socket.connect_attempts >= 2
    assert snapshot["restart_count"] >= 1
