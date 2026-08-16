from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import EmailLoginChallengeRecord, UserAccountRecord
from app.auth.service import EmailAuthService, InvalidLoginCodeError, normalize_email
from app.db import Base
from app.runtime.health import HealthRegistry
from app.web import create_app
from app.web.auth import AuthGuardMiddleware


class FakeLoginCodeSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, UUID, int]] = []
        self.closed = False

    async def send_login_code(
        self,
        *,
        email: str,
        code: str,
        challenge_id: UUID,
        ttl_seconds: int,
    ) -> None:
        self.messages.append((email, code, challenge_id, ttl_seconds))

    async def close(self) -> None:
        self.closed = True


async def _auth_fixture(*, max_attempts: int = 5):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sender = FakeLoginCodeSender()
    service = EmailAuthService(
        session_factory=factory,
        sender=sender,
        secret_key="test-auth-secret-key-that-is-at-least-32-bytes-long",
        login_code_ttl_seconds=600,
        resend_cooldown_seconds=60,
        max_attempts=max_attempts,
        session_ttl_days=30,
    )
    return engine, factory, sender, service


def test_email_normalization_is_stable_and_rejects_malformed_addresses() -> None:
    assert normalize_email("  USER@Example.COM ") == "user@example.com"
    assert normalize_email("user@例子.测试") == "user@xn--fsqu00a.xn--0zwm56d"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")
    with pytest.raises(ValueError):
        normalize_email("user @example.com")


@pytest.mark.asyncio
async def test_login_code_attempt_limit_is_persisted_and_session_can_be_revoked() -> None:
    engine, factory, sender, service = await _auth_fixture(max_attempts=2)
    try:
        first = await service.request_login_code("USER@example.com")
        assert first.sent is True
        assert len(sender.messages) == 1
        email, code, _, ttl = sender.messages[-1]
        assert email == "user@example.com"
        assert len(code) == 6 and code.isdigit()
        assert ttl == 600

        cooldown = await service.request_login_code("user@example.com")
        assert cooldown.sent is False
        assert cooldown.retry_after_seconds > 0
        assert len(sender.messages) == 1

        with pytest.raises(InvalidLoginCodeError):
            await service.verify_login_code(email, "000000" if code != "000000" else "999999")
        async with factory() as session:
            challenge = await session.scalar(
                select(EmailLoginChallengeRecord)
                .where(EmailLoginChallengeRecord.email == email)
                .order_by(EmailLoginChallengeRecord.created_at.desc())
                .limit(1)
            )
            assert challenge is not None
            assert challenge.attempt_count == 1
            assert challenge.consumed_at is None

        with pytest.raises(InvalidLoginCodeError):
            await service.verify_login_code(email, "111111" if code != "111111" else "888888")
        async with factory() as session:
            exhausted = await session.scalar(
                select(EmailLoginChallengeRecord)
                .where(EmailLoginChallengeRecord.email == email)
                .order_by(EmailLoginChallengeRecord.created_at.desc())
                .limit(1)
            )
            assert exhausted is not None
            assert exhausted.attempt_count == 2
            assert exhausted.consumed_at is not None

        with pytest.raises(InvalidLoginCodeError):
            await service.verify_login_code(email, code)

        replacement = await service.request_login_code(email)
        assert replacement.sent is True
        _, replacement_code, _, _ = sender.messages[-1]
        verified = await service.verify_login_code(email, replacement_code)
        assert verified.user.email == email
        assert await service.authenticate(verified.token) == verified.user

        async with factory() as session:
            users = list((await session.scalars(select(UserAccountRecord))).all())
            assert len(users) == 1
            assert users[0].email == email

        await service.logout(verified.token)
        assert await service.authenticate(verified.token) is None
    finally:
        await service.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_api_protects_business_routes_and_sets_http_only_cookie(tmp_path) -> None:
    engine, factory, sender, service = await _auth_fixture()
    try:
        health = HealthRegistry()
        app = create_app(
            factory,
            health,
            frontend_dist=tmp_path / "missing",
            auth_service=service,
            auth_enabled=True,
            auth_cookie_secure=False,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/api/matches")).status_code == 401
            assert (await client.get("/metrics")).status_code == 401

            initial = await client.get("/api/auth/session")
            assert initial.status_code == 200
            assert initial.json() == {"enabled": True, "authenticated": False, "user": None}

            requested = await client.post(
                "/api/auth/request-code", json={"email": "viewer@example.com"}
            )
            assert requested.status_code == 202
            assert requested.json()["accepted"] is True
            code = sender.messages[-1][1]

            verified = await client.post(
                "/api/auth/verify-code",
                json={"email": "viewer@example.com", "code": code},
            )
            assert verified.status_code == 200
            assert verified.json()["authenticated"] is True
            cookie = verified.headers["set-cookie"].lower()
            assert "httponly" in cookie
            assert "samesite=strict" in cookie

            session = await client.get("/api/auth/session")
            assert session.status_code == 200
            assert session.json()["user"]["email"] == "viewer@example.com"
            assert (await client.get("/api/matches")).status_code == 200
            assert (await client.get("/metrics")).status_code == 200

            logged_out = await client.post("/api/auth/logout")
            assert logged_out.status_code == 200
            assert (await client.get("/api/matches")).status_code == 401
    finally:
        await service.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_guard_rejects_unauthenticated_websocket() -> None:
    engine, _, _, service = await _auth_fixture()
    called = False
    sent: list[dict] = []

    async def inner(scope, receive, send) -> None:
        nonlocal called
        called = True

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/ws/status",
        "raw_path": b"/ws/status",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "subprotocols": [],
        "state": {},
    }
    try:
        middleware = AuthGuardMiddleware(inner, service=service, enabled=True)
        await middleware(scope, receive, send)  # type: ignore[arg-type]
        assert called is False
        assert sent == [
            {
                "type": "websocket.close",
                "code": 4401,
                "reason": "authentication required",
            }
        ]
    finally:
        await service.close()
        await engine.dispose()
