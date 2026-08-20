"""Structured models for the local QQ Bot bridge protocol."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QQ_SCOPE_C2C = "c2c"
QQ_SCOPE_GROUP = "group"
QQScope = Literal["c2c", "group"]


class QQBotAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_id: str
    app_secret: str
    # Returned by the official QR connector.  New user-owned accounts use it
    # as their C2C notification target; legacy shared accounts leave it empty.
    user_openid: str | None = None
    owner_user_id: str | None = None
    account_mode: str = "SHARED"
    created_at: datetime


class QQContact(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: QQScope
    target_id: str
    label: str | None = None
    subscribed: bool = True
    first_seen_at: datetime
    last_seen_at: datetime

    @property
    def key(self) -> tuple[str, str]:
        return (self.scope, self.target_id)


class QQInboundMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The bridge may host several user-owned bots.  Legacy event fixtures omit
    # this field and continue to route through the first configured account.
    account_id: str | None = None
    event_type: Literal["MESSAGE", "FRIEND_ADD"] = "MESSAGE"
    event_cursor: int
    scope: QQScope
    target_id: str
    sender_id: str
    message_id: str | None = None
    text: str = ""
    scene_param: str | None = None
    sender_name: str | None = None
    bot_mentioned: bool = False
    mentions: tuple[str, ...] = ()
    timestamp: datetime | None = None


class QQBridgeEventBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[QQInboundMessage, ...] = ()
    cursor: int = 0


class QQBridgeHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool = False
    status: str = "stopped"
    message: str | None = None
    account_count: int = 0
    gateway_connected: bool = False
    buffered_events: int = Field(default=0, ge=0)


def parse_qq_target_entries(entries: tuple[str, ...]) -> tuple[QQContact, ...]:
    """Parse ``c2c:<openid>`` / ``group:<group_openid>`` configuration entries."""
    now = datetime.now(UTC)
    contacts = []
    for entry in entries:
        scope, separator, target_id = entry.partition(":")
        if not separator or scope not in {"c2c", "group"} or not target_id.strip():
            raise ValueError(
                f"QQ target must be c2c:<openid> or group:<group_openid>, got: {entry!r}"
            )
        target_id = target_id.strip()
        contacts.append(
            QQContact(
                scope=scope,  # type: ignore[arg-type]
                target_id=target_id,
                subscribed=True,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    return tuple(contacts)
