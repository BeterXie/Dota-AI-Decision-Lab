import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.maintenance import prune_auth_records
from app.auth.models import AuthSessionRecord, EmailLoginChallengeRecord, UserAccountRecord
from app.auth.service import EmailAuthService
from app.db import Base
from app.runtime.health import HealthRegistry
from app.web import create_app


class _RecordingSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, UUID, int]] = []

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
        return None


class _BlockingSender(_RecordingSender):
    def __init__(self) -> None:
        super().__init__()
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def send_login_code(
        self,
        *,
        email: str,
        code: str,
        challenge_id: UUID,
        ttl_seconds: int,
    ) -> None:
        self.messages.append((email, code, challenge_id, ttl_seconds))
        if email == "slow@example.com":
            self.first_started.set()
            await self.release_first.wait()


async def _fixture(sender=None, **service_kwargs):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sender = sender or _RecordingSender()
    service = EmailAuthService(
        session_factory=factory,
        sender=sender,
        secret_key="test-auth-secret-key-that-is-at-least-32-bytes-long",
        **service_kwargs,
    )
    return engine, factory, sender, service


@pytest.mark.asyncio
async def test_slow_email_delivery_does_not_block_unrelated_email() -> None:
    sender = _BlockingSender()
    engine, _, _, service = await _fixture(
        sender,
        source_rate_limit_max_requests=20,
        global_rate_limit_max_requests=20,
    )
    try:
        assert service._challenge_lock("slow@example.com") is not service._challenge_lock(
            "fast@example.com"
        )
        slow = asyncio.create_task(
            service.request_login_code("slow@example.com", request_source="127.0.0.1")
        )
        await asyncio.wait_for(sender.first_started.wait(), timeout=1)
        fast = await asyncio.wait_for(
            service.request_login_code("fast@example.com", request_source="127.0.0.1"),
            timeout=1,
        )
        assert fast.sent is True
        assert not slow.done()
        sender.release_first.set()
        assert (await slow).sent is True
    finally:
        sender.release_first.set()
        await service.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_request_code_rate_limits_rotating_emails_from_same_direct_client(tmp_path) -> None:
    engine, factory, sender, service = await _fixture(
        source_rate_limit_max_requests=2,
        source_rate_limit_window_seconds=60,
        global_rate_limit_max_requests=100,
        global_rate_limit_window_seconds=60,
    )
    app = create_app(
        factory,
        HealthRegistry(),
        frontend_dist=tmp_path / "missing",
        auth_service=service,
        auth_enabled=True,
        auth_cookie_secure=False,
    )
    try:
        transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/auth/request-code", json={"email": "one@example.com"})
            second = await client.post("/api/auth/request-code", json={"email": "two@example.com"})
            blocked = await client.post(
                "/api/auth/request-code",
                json={"email": "three@example.com"},
            )
        assert first.status_code == 202
        assert second.status_code == 202
        assert blocked.status_code == 429
        assert blocked.json() == {"detail": "too many login code requests"}
        assert int(blocked.headers["retry-after"]) >= 1
        assert len(sender.messages) == 2
    finally:
        await service.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_auth_maintenance_prunes_only_inactive_records_past_retention() -> None:
    engine, factory, _, service = await _fixture()
    now = datetime.now(UTC)
    try:
        async with factory.begin() as session:
            user = UserAccountRecord(
                email="retention@example.com",
                email_verified_at=now,
                last_login_at=now,
                created_at=now,
            )
            session.add(user)
            await session.flush()
            old = now - timedelta(days=61)
            recent = now - timedelta(days=2)
            session.add_all(
                [
                    EmailLoginChallengeRecord(
                        email="old@example.com",
                        code_digest="a" * 64,
                        expires_at=old,
                        attempt_count=1,
                        max_attempts=5,
                        consumed_at=old,
                        delivery_status="SENT",
                        created_at=old,
                    ),
                    EmailLoginChallengeRecord(
                        email="recent@example.com",
                        code_digest="b" * 64,
                        expires_at=recent,
                        attempt_count=1,
                        max_attempts=5,
                        consumed_at=recent,
                        delivery_status="SENT",
                        created_at=recent,
                    ),
                    AuthSessionRecord(
                        user_id=user.id,
                        token_digest="c" * 64,
                        expires_at=old,
                        last_seen_at=old,
                        created_at=old,
                    ),
                    AuthSessionRecord(
                        user_id=user.id,
                        token_digest="d" * 64,
                        expires_at=now + timedelta(days=1),
                        last_seen_at=now,
                        created_at=now,
                    ),
                ]
            )

        async with factory.begin() as session:
            result = await prune_auth_records(
                session,
                now=now,
                challenge_retention_days=30,
                session_retention_days=30,
            )
        assert result.login_challenges_deleted == 1
        assert result.sessions_deleted == 1

        async with factory() as session:
            challenge_count = await session.scalar(select(func.count(EmailLoginChallengeRecord.id)))
            session_count = await session.scalar(select(func.count(AuthSessionRecord.id)))
        assert challenge_count == 1
        assert session_count == 1
    finally:
        await service.close()
        await engine.dispose()
