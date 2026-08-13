import json

import pytest

from app.providers.raybet.socket import RayBetSocketClient


class _Connection:
    def __init__(self, publish: dict) -> None:
        self._responses = iter(
            (
                json.dumps({"rid": 1}),
                json.dumps(publish),
                json.dumps({"rid": 2}),
            )
        )
        self.sent: list[str] = []

    async def send(self, value: str) -> None:
        self.sent.append(value)

    async def recv(self) -> str:
        return next(self._responses)


class _ConnectContext:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _Connection:
        return self._connection

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.mark.asyncio
async def test_publish_before_subscribe_ack_is_delivered_after_handshake(monkeypatch) -> None:
    publish = {
        "event": "#publish",
        "data": {
            "channel": "match",
            "data": {"source": "odds", "odds": [{"id": 1, "match_id": 2, "odds": "1.90"}]},
        },
    }
    connection = _Connection(publish)

    def fake_connect(_self):
        return _ConnectContext(connection)

    monkeypatch.setattr(RayBetSocketClient, "_connect", fake_connect)
    client = RayBetSocketClient("wss://recorded.invalid", "https://recorded.invalid")
    delivered: list[dict] = []
    states: list[str] = []

    async def on_publish(message: dict) -> None:
        delivered.append(message)
        await client.stop()

    async def on_state(state: str, _error: str | None) -> None:
        states.append(state)

    await client.run(on_publish, on_state)

    assert delivered == [publish]
    assert states == ["CONNECTING", "CONNECTED"]
    assert any('"#subscribe"' in item for item in connection.sent)
