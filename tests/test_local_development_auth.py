from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.development import local_development_auth_from_environment
from app.config import Settings
from app.db import Base
from app.entitlements import AI_DECISIONS_ENTITLEMENT, REALTIME_NOTIFICATIONS_ENTITLEMENT
from app.runtime.health import HealthRegistry
from app.web import create_app


def _read_code(path: Path) -> str:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values["code"]


def test_local_development_auth_environment_is_explicit(monkeypatch, tmp_path) -> None:
    code_path = tmp_path / "login-code.txt"
    monkeypatch.setenv("DOTA_LOCAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("DOTA_LOCAL_AUTH_EMAIL", "DEV@LOCALHOST")
    monkeypatch.setenv("DOTA_LOCAL_AUTH_CODE_PATH", str(code_path))

    config = local_development_auth_from_environment()

    assert config.enabled is True
    assert config.pro_email == "dev@localhost"
    assert config.code_path == code_path

    monkeypatch.setenv("DOTA_LOCAL_AUTH_ENABLED", "sometimes")
    with pytest.raises(RuntimeError, match="DOTA_LOCAL_AUTH_ENABLED"):
        local_development_auth_from_environment()


@pytest.mark.asyncio
async def test_local_development_login_uses_real_session_and_auto_grants_only_pro_email(
    monkeypatch,
    tmp_path,
) -> None:
    code_path = tmp_path / "local-login-code.txt"
    monkeypatch.setenv("DOTA_LOCAL_AUTH_ENABLED", "1")
    monkeypatch.setenv("DOTA_LOCAL_AUTH_EMAIL", "dev@localhost")
    monkeypatch.setenv("DOTA_LOCAL_AUTH_CODE_PATH", str(code_path))

    settings = Settings(
        _env_file=None,
        auth_enabled=True,
        auth_secret_key="local-development-auth-secret-that-is-long-enough",
        auth_cookie_secure=False,
        host="127.0.0.1",
    )
    assert settings.resend_api_key is None
    assert settings.resend_from is None

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        app = create_app(
            factory,
            HealthRegistry(),
            frontend_dist=tmp_path / "missing",
            settings=settings,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            requested = await client.post(
                "/api/auth/request-code",
                json={"email": "dev@localhost"},
            )
            assert requested.status_code == 202
            assert code_path.exists()

            verified = await client.post(
                "/api/auth/verify-code",
                json={"email": "dev@localhost", "code": _read_code(code_path)},
            )
            assert verified.status_code == 200
            assert verified.json()["authenticated"] is True
            assert verified.json()["entitlements"] == [
                AI_DECISIONS_ENTITLEMENT,
                REALTIME_NOTIFICATIONS_ENTITLEMENT,
            ]
            assert "httponly" in verified.headers["set-cookie"].lower()
            assert "samesite=strict" in verified.headers["set-cookie"].lower()

            session = await client.get("/api/auth/session")
            assert session.status_code == 200
            assert session.json()["user"]["email"] == "dev@localhost"
            assert session.json()["entitlements"] == [
                AI_DECISIONS_ENTITLEMENT,
                REALTIME_NOTIFICATIONS_ENTITLEMENT,
            ]

            assert (await client.post("/api/auth/logout")).status_code == 200

            free_requested = await client.post(
                "/api/auth/request-code",
                json={"email": "free@localhost"},
            )
            assert free_requested.status_code == 202
            free_verified = await client.post(
                "/api/auth/verify-code",
                json={"email": "free@localhost", "code": _read_code(code_path)},
            )
            assert free_verified.status_code == 200
            assert free_verified.json()["authenticated"] is True
            assert free_verified.json()["entitlements"] == []
    finally:
        await engine.dispose()
