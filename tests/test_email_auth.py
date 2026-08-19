from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import EmailLoginChallengeRecord, UserAccountRecord
from app.auth.service import EmailAuthService, InvalidLoginCodeError, normalize_email
from app.db import Base
from app.entitlements import AI_DECISIONS_ENTITLEMENT, EntitlementService
from app.models import CanonicalMap, MapResultRecord
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
    for invalid in (
        "not-an-email",
        "user @example.com",
        ".user@example.com",
        "user.@example.com",
        "user..name@example.com",
    ):
        with pytest.raises(ValueError):
            normalize_email(invalid)


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
            exhausted_id = exhausted.id

        with pytest.raises(InvalidLoginCodeError):
            await service.verify_login_code(email, code)

        blocked_replacement = await service.request_login_code(email)
        assert blocked_replacement.sent is False
        assert blocked_replacement.retry_after_seconds > 0
        assert len(sender.messages) == 1

        async with factory() as session, session.begin():
            persisted = await session.get(EmailLoginChallengeRecord, exhausted_id)
            assert persisted is not None
            persisted.created_at = persisted.created_at - timedelta(seconds=61)

        replacement = await service.request_login_code(email)
        assert replacement.sent is True
        assert len(sender.messages) == 2
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
async def test_auth_api_keeps_matches_public_and_requires_entitlement_for_ai(tmp_path) -> None:
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
        premium_map_id = UUID("11111111-1111-1111-1111-111111111111")
        async with factory() as session, session.begin():
            session.add(CanonicalMap(id=premium_map_id, map_number=1))
        premium_path = f"/api/maps/{premium_map_id}/ai-decisions"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/api/matches")).status_code == 200
            assert (await client.get("/metrics")).status_code == 401
            assert (await client.get(premium_path)).status_code == 401

            initial = await client.get("/api/auth/session")
            assert initial.status_code == 200
            assert initial.json() == {
                "enabled": True,
                "authenticated": False,
                "user": None,
                "entitlements": [],
                "grants": [],
                "providers": {"email": True, "google": False, "steam": False},
            }

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
            verified_payload = verified.json()
            assert verified_payload["authenticated"] is True
            assert verified_payload["entitlements"] == []
            cookie = verified.headers["set-cookie"].lower()
            assert "httponly" in cookie
            assert "samesite=strict" in cookie

            session = await client.get("/api/auth/session")
            assert session.status_code == 200
            assert session.json()["user"]["email"] == "viewer@example.com"
            assert session.json()["entitlements"] == []
            assert (await client.get("/api/matches")).status_code == 200
            assert (await client.get("/metrics")).status_code == 200

            forbidden = await client.get(premium_path)
            assert forbidden.status_code == 403
            assert forbidden.json() == {
                "detail": "AI Decision access is not granted for this match"
            }

            user_id = UUID(session.json()["user"]["id"])
            await EntitlementService(factory).grant(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                source="test",
            )
            entitled_map = await client.get(premium_path)
            assert entitled_map.status_code == 200
            assert entitled_map.json()["canonical_map_id"] == str(premium_map_id)

            refreshed = await client.get("/api/auth/session")
            assert refreshed.json()["entitlements"] == [AI_DECISIONS_ENTITLEMENT]

            logged_out = await client.post("/api/auth/logout")
            assert logged_out.status_code == 200
            assert (await client.get("/api/matches")).status_code == 200
            assert (await client.get(premium_path)).status_code == 401

            async with factory() as db_session, db_session.begin():
                db_session.add(
                    MapResultRecord(
                        canonical_map_id=premium_map_id,
                        basic_first_usable_at=datetime.now(UTC),
                    )
                )
            settled = await client.get(premium_path)
            assert settled.status_code == 401
            assert settled.json() == {"detail": "authentication required"}
    finally:
        await service.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_guard_keeps_status_websocket_public_and_protects_others() -> None:
    engine, factory, _, service = await _auth_fixture()
    called: list[str] = []
    sent: list[dict] = []

    async def inner(scope, receive, send) -> None:
        called.append(scope["path"])

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    async def send(message: dict) -> None:
        sent.append(message)

    def scope(path: str) -> dict:
        return {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "subprotocols": [],
            "state": {},
        }

    try:
        middleware = AuthGuardMiddleware(
            inner,
            service=service,
            entitlements=EntitlementService(factory),
            enabled=True,
        )
        await middleware(scope("/ws/private"), receive, send)  # type: ignore[arg-type]
        assert called == []
        assert sent == [
            {
                "type": "websocket.close",
                "code": 4401,
                "reason": "authentication required",
            }
        ]

        sent.clear()
        await middleware(scope("/ws/status"), receive, send)  # type: ignore[arg-type]
        assert called == ["/ws/status"]
        assert sent == []
    finally:
        await service.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_disabled_preserves_public_access_but_closes_protected_apis(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        unfinished_map_id = UUID("11111111-1111-1111-1111-111111111111")
        async with factory() as session, session.begin():
            session.add(CanonicalMap(id=unfinished_map_id, map_number=1))
        app = create_app(
            factory,
            HealthRegistry(),
            frontend_dist=tmp_path / "missing",
            auth_enabled=False,
            auth_cookie_secure=False,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            session = await client.get("/api/auth/session")
            assert session.status_code == 200
            assert session.json() == {
                "enabled": False,
                "authenticated": True,
                "user": None,
                "entitlements": [],
                "grants": [],
                "providers": {"email": False, "google": False, "steam": False},
            }
            assert (await client.get("/api/matches")).status_code == 200
            assert (await client.get("/metrics")).status_code == 503
            premium = await client.get(f"/api/maps/{unfinished_map_id}/ai-decisions")
            assert premium.status_code == 401
            assert premium.json() == {"detail": "authentication required"}
    finally:
        await engine.dispose()
