"""Structured models for the official Tencent WeChat ClawBot HTTP protocol.

Wire contract mirrors the official MIT plugin
``@tencent-weixin/openclaw-weixin`` (channel version 2.x): JSON over HTTP to
``https://ilinkai.weixin.qq.com`` with ``AuthorizationType: ilink_bot_token``.
Only the direct-chat subset needed by Dota-AI-Decision-Lab is modeled here.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

WECHAT_BOT_TYPE = "3"
WECHAT_BASE_URL = "https://ilinkai.weixin.qq.com"
WECHAT_APP_ID = "bot"
WECHAT_CHANNEL_VERSION = "2.4.6"

MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2
ITEM_TYPE_TEXT = 1
MESSAGE_STATE_FINISH = 2


class WeChatAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    token: str
    base_url: str = WECHAT_BASE_URL
    # ``owner_user_id`` is the authenticated Dota Lab account that completed
    # this QR login.  It is local metadata only; the bearer token remains in
    # the private state directory.
    owner_user_id: str | None = None
    account_mode: str = "SHARED"
    user_id: str | None = None
    context_token: str | None = None
    created_at: datetime


class WeChatContact(BaseModel):
    """A direct-chat peer on a shared WeChat ClawBot account."""

    model_config = ConfigDict(frozen=True)

    account_id: str
    user_id: str
    context_token: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime


class WeChatInboundMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: int | None = None
    from_user_id: str | None = None
    to_user_id: str | None = None
    context_token: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    group_id: str | None = None
    message_type: int | None = None
    text: str = ""
    created_at_ms: int | None = None


class WeChatUpdateBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[WeChatInboundMessage, ...] = ()
    cursor: str = ""
    ret: int = 0
    error_code: int | None = None
    error_message: str | None = None
    long_poll_timeout_ms: int | None = None


class WeChatQrStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str = "wait"
    bot_token: str | None = None
    account_id: str | None = None
    base_url: str | None = None
    user_id: str | None = None
    redirect_host: str | None = None


class WeChatQrStart(BaseModel):
    model_config = ConfigDict(frozen=True)

    qrcode: str
    qrcode_url: str


class WeChatTextRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    to_user_id: str
    text: str
    context_token: str | None = None
    run_id: str | None = None
    client_id: str = Field(default="")
