import asyncio
import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthSessionRecord, EmailLoginChallengeRecord, UserAccountRecord
from app.time import ensure_utc

SESSION_COOKIE_NAME = "dota_session"
_LOGIN_CODE_DIGITS = 6
_EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class LoginCodeSender(Protocol):
    async def send_login_code(
        self,
        *,
        email: str,
        code: str,
        challenge_id: UUID,
        ttl_seconds: int,
    ) -> None: ...

    async def close(self) -> None: ...


class InvalidEmailError(ValueError):
    pass


class InvalidLoginCodeError(ValueError):
    pass


class AuthDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    email: str
    email_verified_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LoginCodeRequestResult:
    sent: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class LoginVerificationResult:
    token: str
    expires_at: datetime
    user: AuthenticatedUser


class EmailAuthService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        sender: LoginCodeSender,
        secret_key: str,
        login_code_ttl_seconds: int = 600,
        resend_cooldown_seconds: int = 60,
        max_attempts: int = 5,
        session_ttl_days: int = 30,
    ) -> None:
        if len(secret_key.encode("utf-8")) < 32:
            raise ValueError("auth secret key must be at least 32 bytes")
        self._session_factory = session_factory
        self._sender = sender
        self._secret_key = secret_key.encode("utf-8")
        self._login_code_ttl_seconds = login_code_ttl_seconds
        self._resend_cooldown_seconds = resend_cooldown_seconds
        self._max_attempts = max_attempts
        self._session_ttl_days = session_ttl_days
        # Login traffic is tiny; serializing challenge mutation inside one runtime
        # closes request/verify races on SQLite and complements row locks on Postgres.
        self._challenge_lock = asyncio.Lock()

    async def request_login_code(self, raw_email: str) -> LoginCodeRequestResult:
        email = normalize_email(raw_email)
        now = datetime.now(UTC)
        async with self._challenge_lock:
            async with self._session_factory() as session, session.begin():
                latest = await session.scalar(
                    select(EmailLoginChallengeRecord)
                    .where(EmailLoginChallengeRecord.email == email)
                    .order_by(EmailLoginChallengeRecord.created_at.desc())
                    .limit(1)
                    .with_for_update()
                )
                # Rate-limit every successfully delivered challenge, even after it
                # has been consumed by too many guesses. Otherwise an attacker can
                # immediately request another code and reset the attempt budget.
                # A delivery failure is the only case that may retry immediately.
                if latest is not None and latest.delivery_status != "FAILED":
                    elapsed = (now - ensure_utc(latest.created_at)).total_seconds()
                    remaining = max(0, int(self._resend_cooldown_seconds - elapsed + 0.999))
                    if remaining > 0:
                        return LoginCodeRequestResult(sent=False, retry_after_seconds=remaining)
                if latest is not None and latest.consumed_at is None:
                    latest.consumed_at = now

                challenge_id = uuid4()
                code = f"{secrets.randbelow(10**_LOGIN_CODE_DIGITS):0{_LOGIN_CODE_DIGITS}d}"
                challenge = EmailLoginChallengeRecord(
                    id=challenge_id,
                    email=email,
                    code_digest=self._code_digest(challenge_id, code),
                    expires_at=now + timedelta(seconds=self._login_code_ttl_seconds),
                    attempt_count=0,
                    max_attempts=self._max_attempts,
                    delivery_status="PENDING",
                    created_at=now,
                )
                session.add(challenge)

            try:
                await self._sender.send_login_code(
                    email=email,
                    code=code,
                    challenge_id=challenge_id,
                    ttl_seconds=self._login_code_ttl_seconds,
                )
            except Exception as exc:
                async with self._session_factory() as session, session.begin():
                    failed = await session.get(EmailLoginChallengeRecord, challenge_id)
                    if failed is not None:
                        failed.delivery_status = "FAILED"
                        failed.last_error = f"{type(exc).__name__}: {exc}"
                        failed.consumed_at = datetime.now(UTC)
                raise AuthDeliveryError("failed to send login email") from exc

            async with self._session_factory() as session, session.begin():
                delivered = await session.get(EmailLoginChallengeRecord, challenge_id)
                if delivered is None:
                    raise AuthDeliveryError("login challenge disappeared after delivery")
                delivered.delivery_status = "SENT"
                delivered.delivered_at = datetime.now(UTC)
                delivered.last_error = None

        return LoginCodeRequestResult(sent=True, retry_after_seconds=self._resend_cooldown_seconds)

    async def verify_login_code(self, raw_email: str, raw_code: str) -> LoginVerificationResult:
        email = normalize_email(raw_email)
        code = raw_code.strip()
        now = datetime.now(UTC)
        failure: str | None = None
        verification: LoginVerificationResult | None = None

        async with self._challenge_lock:
            async with self._session_factory() as session, session.begin():
                challenge = await session.scalar(
                    select(EmailLoginChallengeRecord)
                    .where(
                        EmailLoginChallengeRecord.email == email,
                        EmailLoginChallengeRecord.delivery_status == "SENT",
                        EmailLoginChallengeRecord.consumed_at.is_(None),
                    )
                    .order_by(EmailLoginChallengeRecord.created_at.desc())
                    .limit(1)
                    .with_for_update()
                )
                if challenge is None:
                    failure = "invalid or expired login code"
                elif ensure_utc(challenge.expires_at) <= now:
                    challenge.consumed_at = now
                    failure = "invalid or expired login code"
                elif challenge.attempt_count >= challenge.max_attempts:
                    challenge.consumed_at = now
                    failure = "invalid or expired login code"
                else:
                    challenge.attempt_count += 1
                    supplied = self._code_digest(challenge.id, code)
                    if not hmac.compare_digest(challenge.code_digest, supplied):
                        if challenge.attempt_count >= challenge.max_attempts:
                            challenge.consumed_at = now
                        failure = "invalid or expired login code"
                    else:
                        challenge.consumed_at = now
                        user = await session.scalar(
                            select(UserAccountRecord)
                            .where(UserAccountRecord.email == email)
                            .limit(1)
                            .with_for_update()
                        )
                        if user is not None and user.disabled_at is not None:
                            failure = "account is disabled"
                        else:
                            if user is None:
                                user = UserAccountRecord(
                                    email=email,
                                    email_verified_at=now,
                                    last_login_at=now,
                                    created_at=now,
                                )
                                session.add(user)
                                await session.flush()
                            else:
                                user.email_verified_at = now
                                user.last_login_at = now

                            token = secrets.token_urlsafe(48)
                            expires_at = now + timedelta(days=self._session_ttl_days)
                            session.add(
                                AuthSessionRecord(
                                    user_id=user.id,
                                    token_digest=_token_digest(token),
                                    expires_at=expires_at,
                                    last_seen_at=now,
                                    created_at=now,
                                )
                            )
                            verification = LoginVerificationResult(
                                token=token,
                                expires_at=expires_at,
                                user=_authenticated_user(user),
                            )

        if failure is not None:
            raise InvalidLoginCodeError(failure)
        if verification is None:
            raise RuntimeError("login verification completed without a result")
        return verification

    async def authenticate(self, token: str | None) -> AuthenticatedUser | None:
        if not token:
            return None
        digest = _token_digest(token)
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(AuthSessionRecord, UserAccountRecord)
                    .join(UserAccountRecord, UserAccountRecord.id == AuthSessionRecord.user_id)
                    .where(
                        AuthSessionRecord.token_digest == digest,
                        AuthSessionRecord.revoked_at.is_(None),
                        AuthSessionRecord.expires_at > now,
                        UserAccountRecord.disabled_at.is_(None),
                    )
                    .limit(1)
                )
            ).first()
            if row is None:
                return None
            auth_session, user = row
            if (now - ensure_utc(auth_session.last_seen_at)).total_seconds() >= 300:
                auth_session.last_seen_at = now
            return _authenticated_user(user)

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        digest = _token_digest(token)
        async with self._session_factory() as session, session.begin():
            auth_session = await session.scalar(
                select(AuthSessionRecord)
                .where(
                    AuthSessionRecord.token_digest == digest,
                    AuthSessionRecord.revoked_at.is_(None),
                )
                .limit(1)
                .with_for_update()
            )
            if auth_session is not None:
                auth_session.revoked_at = datetime.now(UTC)

    async def close(self) -> None:
        await self._sender.close()

    def _code_digest(self, challenge_id: UUID, code: str) -> str:
        payload = f"email-login:{challenge_id}:{code}".encode()
        return hmac.new(self._secret_key, payload, hashlib.sha256).hexdigest()


def normalize_email(raw_email: str) -> str:
    value = unicodedata.normalize("NFKC", raw_email).strip()
    if not value or len(value) > 320 or any(char.isspace() or ord(char) < 32 for char in value):
        raise InvalidEmailError("invalid email address")
    if value.count("@") != 1:
        raise InvalidEmailError("invalid email address")
    local, domain = value.rsplit("@", 1)
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not _EMAIL_LOCAL_RE.fullmatch(local)
    ):
        raise InvalidEmailError("invalid email address")
    try:
        ascii_domain = domain.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidEmailError("invalid email address") from exc
    if not ascii_domain or len(ascii_domain) > 253:
        raise InvalidEmailError("invalid email address")
    labels = ascii_domain.split(".")
    if any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        raise InvalidEmailError("invalid email address")
    return f"{local.lower()}@{ascii_domain}"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _authenticated_user(user: UserAccountRecord) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        email_verified_at=ensure_utc(user.email_verified_at),
        created_at=ensure_utc(user.created_at),
    )
