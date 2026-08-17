"""Supervised subprocess runner for the QQ Bot Node bridge."""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

from app.config import Settings
from app.providers.qq_bot.bridge_client import QQBridgeClient
from app.providers.qq_bot.storage import QQBotStore
from app.runtime.health import HealthRegistry

logger = structlog.get_logger()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BRIDGE_SCRIPT = PROJECT_ROOT / "tools" / "qq_bot_bridge.mjs"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class QQBotBridgeSetupError(RuntimeError):
    pass


class QQBotBridgeRunner:
    """Keep one Node bridge process alive for the bound QQ Bot account.

    The bridge uses the official SDK installed by the harness profile
    (``~/.dsh/profiles/qqbot``). The control API is deliberately restricted to
    loopback and authenticated with an owner-only bearer token shared with the
    Python runtime.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        store: QQBotStore,
        health: HealthRegistry | None = None,
        script: Path | None = None,
        node_bin: str | None = None,
        sdk_index: Path | None = None,
    ) -> None:
        if settings.qq_bot_bridge_host not in _LOOPBACK_HOSTS:
            raise QQBotBridgeSetupError("QQ_BOT_BRIDGE_HOST must remain loopback")
        self._settings = settings
        self._store = store
        self._health = health
        self._script = (script or DEFAULT_BRIDGE_SCRIPT).resolve()
        self._node_bin = node_bin or shutil.which("node")
        self._sdk_index = sdk_index or resolve_qq_sdk_index(settings)
        self._bridge_token = store.bridge_token()
        self._stop = asyncio.Event()
        self._process: asyncio.subprocess.Process | None = None
        self._drain_task: asyncio.Task | None = None

    async def run(self) -> None:
        if not self._node_bin:
            await self._update_health(
                "ACTION_REQUIRED",
                message="Node.js is required for the QQ Bot bridge",
            )
            raise QQBotBridgeSetupError("node executable not found")
        if not self._script.is_file():
            raise QQBotBridgeSetupError(f"QQ bridge script not found: {self._script}")
        if not self._sdk_index.is_file():
            raise QQBotBridgeSetupError(
                f"QQ SDK entry not found: {self._sdk_index}; "
                "run: npm install --prefix qqbot_bridge @tencent-connect/qqbot-nodejs "
                "or set QQ_BOT_SDK_ROOT"
            )

        self._stop.clear()
        backoff = 1.0
        while not self._stop.is_set():
            accounts = list(self._store.accounts())
            if not accounts:
                await self._update_health(
                    "ACTION_REQUIRED",
                    message="run: python -m tools.qq_bot login",
                )
                await self._sleep(15)
                continue
            env = self._bridge_env(accounts[0].app_id)
            await self._update_health(
                "DEGRADED",
                message="QQ bridge starting",
                account_id=accounts[0].app_id,
            )
            try:
                await self._run_process(env)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._update_health(
                    "DEGRADED",
                    message=f"{type(exc).__name__}: {exc}",
                )
            if self._stop.is_set():
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
        self._process = None
        self._drain_task = None

    async def _run_process(self, env: dict[str, str]) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._process = await asyncio.create_subprocess_exec(
            self._node_bin,
            str(self._script),
            cwd=PROJECT_ROOT,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=creationflags,
        )
        self._drain_task = asyncio.create_task(self._drain(self._process))
        try:
            await self._wait_until_ready()
            await self._process.wait()
        finally:
            await self._wait_for_drain()
        logger.info("qq_bot_bridge_exited", returncode=self._process.returncode)
        await self._update_health(
            "DEGRADED",
            message=f"QQ bridge exited with code {self._process.returncode}",
        )

    async def _wait_until_ready(self) -> None:
        deadline = (
            asyncio.get_running_loop().time() + self._settings.qq_bot_bridge_startup_timeout_seconds
        )
        client = QQBridgeClient(
            base_url=f"http://{self._settings.qq_bot_bridge_host}:"
            f"{self._settings.qq_bot_bridge_port}",
            timeout_seconds=2.0,
            token=self._bridge_token,
        )
        try:
            while not self._stop.is_set():
                if self._process is not None and self._process.returncode is not None:
                    return
                try:
                    health = await client.health()
                    if health.gateway_connected:
                        await self._update_health(
                            "READY",
                            account_count=health.account_count,
                            buffered_events=health.buffered_events,
                        )
                        return
                except Exception as exc:
                    logger.debug("qq_bot_bridge_health_check_failed", error=str(exc))
                if asyncio.get_running_loop().time() >= deadline:
                    await self._update_health(
                        "DEGRADED",
                        message="QQ bridge did not connect to the QQ gateway in time",
                    )
                    return
                await asyncio.sleep(0.5)
        finally:
            await client.close()

    async def _drain(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            raise QQBotBridgeSetupError("QQ bridge stdout pipe is unavailable")
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                logger.info("qq_bot_bridge", line=line[:500])

    async def _wait_for_drain(self) -> None:
        if self._drain_task is None:
            return
        try:
            await asyncio.wait_for(self._drain_task, timeout=2)
        except TimeoutError:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
        self._drain_task = None

    def _bridge_env(self, account_id: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "QQ_BOT_STATE_DIR": str(self._store.root.resolve()),
                "QQ_BOT_SDK_INDEX": str(self._sdk_index),
                "QQ_BOT_BRIDGE_HOST": self._settings.qq_bot_bridge_host,
                "QQ_BOT_BRIDGE_PORT": str(self._settings.qq_bot_bridge_port),
                "QQ_BOT_BRIDGE_TOKEN": self._bridge_token,
                "QQ_BOT_ACCOUNT_ID": account_id,
                "QQ_BOT_GROUP_REQUIRE_MENTION": (
                    "1" if self._settings.qq_bot_group_require_mention else "0"
                ),
                "QQ_BOT_ALLOWED_C2C": self._settings.qq_bot_allowed_c2c,
                "QQ_BOT_ALLOWED_GROUPS": self._settings.qq_bot_allowed_groups,
            }
        )
        return env

    async def _update_health(
        self, status: str, *, message: str | None = None, **metadata: Any
    ) -> None:
        if self._health is None:
            return
        await self._health.dependency("QQ", status, message=message, **metadata)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass


def resolve_qq_sdk_index(settings: Settings) -> Path:
    if settings.qq_bot_sdk_root:
        root = Path(settings.qq_bot_sdk_root).expanduser()
        candidates = (
            root if root.is_file() else root / "dist" / "index.js",
            root / "@tencent-connect" / "qqbot-nodejs" / "dist" / "index.js",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
    candidates = (
        Path.home()
        / ".dsh"
        / "profiles"
        / "qqbot"
        / "node_modules"
        / "@tencent-connect"
        / "qqbot-nodejs"
        / "dist"
        / "index.js",
        PROJECT_ROOT
        / "qqbot_bridge"
        / "node_modules"
        / "@tencent-connect"
        / "qqbot-nodejs"
        / "dist"
        / "index.js",
        PROJECT_ROOT / "node_modules" / "@tencent-connect" / "qqbot-nodejs" / "dist" / "index.js",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0]


def resolve_qq_connector_index(settings: Settings) -> Path:
    if settings.qq_bot_sdk_root:
        root = Path(settings.qq_bot_sdk_root).expanduser()
        if root.is_dir():
            candidates = (
                root / "@tencent-connect" / "qqbot-connector" / "dist" / "esm" / "index.js",
                root
                / "node_modules"
                / "@tencent-connect"
                / "qqbot-connector"
                / "dist"
                / "esm"
                / "index.js",
            )
            for candidate in candidates:
                if candidate.is_file():
                    return candidate.resolve()
    candidates = (
        Path.home()
        / ".dsh"
        / "profiles"
        / "qqbot"
        / "node_modules"
        / "@tencent-connect"
        / "qqbot-connector"
        / "dist"
        / "esm"
        / "index.js",
        PROJECT_ROOT
        / "qqbot_bridge"
        / "node_modules"
        / "@tencent-connect"
        / "qqbot-connector"
        / "dist"
        / "esm"
        / "index.js",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0]
