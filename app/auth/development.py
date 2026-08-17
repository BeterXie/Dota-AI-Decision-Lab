import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.auth.service import normalize_email

LOCAL_AUTH_ENABLED_ENV = "DOTA_LOCAL_AUTH_ENABLED"
LOCAL_AUTH_EMAIL_ENV = "DOTA_LOCAL_AUTH_EMAIL"
LOCAL_AUTH_CODE_PATH_ENV = "DOTA_LOCAL_AUTH_CODE_PATH"
_DEFAULT_PRO_EMAIL = "dev@localhost"
_DEFAULT_CODE_PATH = Path(".runtime/local-login-code.txt")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class LocalDevelopmentAuth:
    enabled: bool
    pro_email: str
    code_path: Path


def local_development_auth_from_environment() -> LocalDevelopmentAuth:
    raw_enabled = os.environ.get(LOCAL_AUTH_ENABLED_ENV, "").strip().lower()
    if raw_enabled in _TRUE_VALUES:
        enabled = True
    elif raw_enabled in _FALSE_VALUES:
        enabled = False
    else:
        raise RuntimeError(
            f"{LOCAL_AUTH_ENABLED_ENV} must be one of 1/true/yes/on or 0/false/no/off"
        )

    # A stale local-development email/path must never affect the normal Resend
    # runtime when the explicit development switch is off.
    if not enabled:
        return LocalDevelopmentAuth(
            enabled=False,
            pro_email=_DEFAULT_PRO_EMAIL,
            code_path=_DEFAULT_CODE_PATH,
        )

    raw_email = os.environ.get(LOCAL_AUTH_EMAIL_ENV, _DEFAULT_PRO_EMAIL)
    pro_email = normalize_email(raw_email)
    raw_code_path = os.environ.get(LOCAL_AUTH_CODE_PATH_ENV, "").strip()
    code_path = Path(raw_code_path) if raw_code_path else _DEFAULT_CODE_PATH
    return LocalDevelopmentAuth(enabled=True, pro_email=pro_email, code_path=code_path)


class LocalLoginCodeSender:
    """Deliver a development OTP into an ignored runtime file instead of email.

    This sender is selected only by the explicit loopback-only development mode.
    The normal EmailAuthService still creates and verifies the one-time challenge,
    so local testing exercises the same session and entitlement path as production.
    """

    def __init__(self, code_path: Path) -> None:
        self._code_path = code_path

    async def send_login_code(
        self,
        *,
        email: str,
        code: str,
        challenge_id: UUID,
        ttl_seconds: int,
    ) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        self._code_path.parent.mkdir(parents=True, exist_ok=True)
        self._code_path.write_text(
            "\n".join(
                (
                    f"email={email}",
                    f"code={code}",
                    f"challenge_id={challenge_id}",
                    f"expires_at={expires_at.isoformat()}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        try:
            self._code_path.chmod(0o600)
        except OSError:
            # Windows ACLs do not map cleanly to POSIX chmod. The file remains
            # under the ignored local .runtime directory either way.
            pass

    async def close(self) -> None:
        return None
