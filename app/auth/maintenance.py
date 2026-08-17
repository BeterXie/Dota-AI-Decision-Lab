from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.auth.models import AuthSessionRecord, EmailLoginChallengeRecord


@dataclass(frozen=True, slots=True)
class AuthMaintenanceResult:
    login_challenges_deleted: int
    sessions_deleted: int


async def prune_auth_records(
    executor: AsyncSession | AsyncConnection,
    *,
    now: datetime | None = None,
    challenge_retention_days: int = 30,
    session_retention_days: int = 30,
) -> AuthMaintenanceResult:
    """Delete only security records that are both inactive and past retention.

    The caller owns the transaction. This lets the periodic database maintenance
    path commit partition and auth-retention work atomically while tests may pass
    a normal AsyncSession.
    """

    if challenge_retention_days < 1 or session_retention_days < 1:
        raise ValueError("authentication retention days must be positive")
    current = now or datetime.now(UTC)
    challenge_cutoff = current - timedelta(days=challenge_retention_days)
    session_cutoff = current - timedelta(days=session_retention_days)

    challenge_result = await executor.execute(
        delete(EmailLoginChallengeRecord).where(
            EmailLoginChallengeRecord.created_at <= challenge_cutoff,
            or_(
                EmailLoginChallengeRecord.expires_at <= challenge_cutoff,
                and_(
                    EmailLoginChallengeRecord.consumed_at.is_not(None),
                    EmailLoginChallengeRecord.consumed_at <= challenge_cutoff,
                ),
            ),
        )
    )
    session_result = await executor.execute(
        delete(AuthSessionRecord).where(
            or_(
                AuthSessionRecord.expires_at <= session_cutoff,
                and_(
                    AuthSessionRecord.revoked_at.is_not(None),
                    AuthSessionRecord.revoked_at <= session_cutoff,
                ),
            )
        )
    )
    return AuthMaintenanceResult(
        login_challenges_deleted=max(challenge_result.rowcount or 0, 0),
        sessions_deleted=max(session_result.rowcount or 0, 0),
    )
