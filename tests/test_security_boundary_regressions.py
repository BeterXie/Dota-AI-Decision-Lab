import os
import stat
from pathlib import Path
from typing import Any, cast

import pytest

from app.config import Settings
from app.providers.qq_bot.bridge_runner import QQBotBridgeRunner, QQBotBridgeSetupError
from app.providers.qq_bot.storage import QQBotStore
from app.web.auth import AuthGuardMiddleware, _websocket_origin_allowed


def test_qq_bridge_token_is_stable_and_owner_only(tmp_path: Path) -> None:
    store = QQBotStore(tmp_path)

    first = store.bridge_token()
    second = store.bridge_token()

    assert first == second
    assert len(first) >= 32
    token_path = tmp_path / "bridge-token.json"
    assert token_path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_qq_bridge_runner_rejects_non_loopback_host(tmp_path: Path) -> None:
    settings = Settings(
        qq_bot_bridge_host="0.0.0.0",
        qq_bot_state_dir=str(tmp_path),
    )
    store = QQBotStore(tmp_path)

    with pytest.raises(QQBotBridgeSetupError, match="must remain loopback"):
        QQBotBridgeRunner(settings, store=store)


def test_websocket_origin_policy_allows_loopback_and_production_same_origin() -> None:
    assert _websocket_origin_allowed(None) is True
    assert _websocket_origin_allowed("http://127.0.0.1:8000") is True
    assert _websocket_origin_allowed("http://localhost:5173") is True
    assert _websocket_origin_allowed("https://[::1]:8443") is True
    assert _websocket_origin_allowed("https://dota.example", "dota.example") is True
    assert _websocket_origin_allowed("https://dota.example:8443", "dota.example:8443") is True
    assert _websocket_origin_allowed("https://dota.example", "api.example") is False
    assert _websocket_origin_allowed("https://dota.example:8443", "dota.example") is False
    assert _websocket_origin_allowed("https://evil.example") is False
    assert _websocket_origin_allowed("null") is False


@pytest.mark.asyncio
async def test_auth_disabled_fails_closed_for_protected_http_routes() -> None:
    inner_called = False

    async def inner(scope: dict[str, Any], receive, send) -> None:
        nonlocal inner_called
        inner_called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = AuthGuardMiddleware(
        inner,
        service=None,
        entitlements=cast(Any, object()),
        enabled=False,
    )
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/jobs/summary",
        "raw_path": b"/api/jobs/summary",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
        "root_path": "",
    }

    await middleware(cast(Any, scope), receive, send)

    assert inner_called is False
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/matches", "/api/access/maps/00000000-0000-0000-0000-000000000001"]
)
async def test_auth_disabled_keeps_explicit_public_http_routes_available(path: str) -> None:
    inner_called = False

    async def inner(scope: dict[str, Any], receive, send) -> None:
        nonlocal inner_called
        inner_called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = AuthGuardMiddleware(
        inner,
        service=None,
        entitlements=cast(Any, object()),
        enabled=False,
    )
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
        "root_path": "",
    }

    await middleware(cast(Any, scope), receive, send)

    assert inner_called is True
    assert sent[0]["status"] == 200
