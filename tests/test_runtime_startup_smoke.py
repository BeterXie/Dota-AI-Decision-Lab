import asyncio
import os
import socket

import httpx
import pytest

from app import main as runtime_main
from app.config import Settings


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_main_run_starts_web_runtime_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("runtime smoke requires the CI PostgreSQL DATABASE_URL")
    port = _free_port()
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        auto_migrate=False,
        run_provider_workers=False,
        wechat_clawbot_enabled=False,
        email_notifications_enabled=False,
        host="127.0.0.1",
        port=port,
        log_level="WARNING",
        ai_min_game_time_seconds=777,
    )
    monkeypatch.setattr(runtime_main, "get_settings", lambda: settings)
    probe_error: list[BaseException] = []

    def install_probe(shutdown: asyncio.Event) -> None:
        async def probe() -> None:
            try:
                async with httpx.AsyncClient(timeout=0.5) as client:
                    for _ in range(80):
                        try:
                            health = await client.get(f"http://127.0.0.1:{port}/health")
                            runtime = await client.get(f"http://127.0.0.1:{port}/api/runtime")
                            if health.status_code == 200 and runtime.status_code == 200:
                                assert health.json()["status"] == "RUNNING"
                                return
                        except httpx.ConnectError, httpx.ReadError:
                            pass
                        await asyncio.sleep(0.05)
                raise AssertionError("runtime web server never became healthy")
            except BaseException as exc:
                probe_error.append(exc)
            finally:
                shutdown.set()

        asyncio.create_task(probe())

    monkeypatch.setattr(runtime_main, "_install_signal_handlers", install_probe)
    await asyncio.wait_for(runtime_main.run(), timeout=15)
    assert not probe_error, repr(probe_error[0]) if probe_error else ""
