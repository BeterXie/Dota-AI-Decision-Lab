import base64
import hashlib
import secrets
from typing import Any
from uuid import uuid4

import httpx

from app.providers.common import create_system_ssl_context
from app.providers.wechat_clawbot.models import (
    ITEM_TYPE_TEXT,
    MESSAGE_STATE_FINISH,
    MESSAGE_TYPE_BOT,
    WECHAT_APP_ID,
    WECHAT_BASE_URL,
    WECHAT_BOT_TYPE,
    WECHAT_CHANNEL_VERSION,
    WeChatAccount,
    WeChatInboundMessage,
    WeChatQrStart,
    WeChatQrStatus,
    WeChatUpdateBatch,
)

CLIENT_VERSION = "132102"  # 2.4.6 encoded as (2<<16)|(4<<8)|6, official wire format


class WeChatClawBotError(RuntimeError):
    pass


class WeChatClawBotClient:
    """Minimal client for the official WeChat ClawBot iLink HTTP API.

    The official ``@tencent-weixin/openclaw-weixin`` channel is a thin wrapper
    around this API. This client implements only the direct-chat subset the
    Dota decision harness needs; it has no OpenClaw dependency.
    """

    def __init__(
        self,
        *,
        base_url: str = WECHAT_BASE_URL,
        bot_agent: str = "Dota-AI-Decision-Lab/0.1.0",
        timeout_seconds: float = 15.0,
        long_poll_timeout_seconds: float = 40.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bot_agent = _sanitize_bot_agent(bot_agent)
        self._timeout_seconds = timeout_seconds
        self._long_poll_timeout_seconds = long_poll_timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            verify=create_system_ssl_context(),
            timeout=httpx.Timeout(timeout_seconds),
        )
        self._started_accounts: set[str] = set()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def base_url(self) -> str:
        return self._base_url

    async def start_qr_login(self) -> WeChatQrStart:
        raw = await self._post(
            f"/ilink/bot/get_bot_qrcode?bot_type={WECHAT_BOT_TYPE}",
            body={"local_token_list": []},
            request_timeout_seconds=self._timeout_seconds,
        )
        if not isinstance(raw, dict) or not raw.get("qrcode"):
            raise WeChatClawBotError("QR login response is missing the qrcode field")
        url = raw.get("qrcode_img_content")
        if not isinstance(url, str) or not url:
            raise WeChatClawBotError("QR login response is missing qrcode_img_content")
        return WeChatQrStart(qrcode=str(raw["qrcode"]), qrcode_url=url)

    async def poll_qr_status(
        self,
        qrcode: str,
        *,
        verify_code: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> WeChatQrStatus:
        path = (
            f"/ilink/bot/get_qrcode_status?qrcode={httpx.QueryParams({'qrcode': qrcode})['qrcode']}"
        )
        if verify_code:
            path += f"&verify_code={httpx.QueryParams({'verify_code': verify_code})['verify_code']}"
        request_base_url = (base_url or self._base_url).rstrip("/")
        client = self._client
        if self._owns_client and request_base_url != self._base_url:
            client = httpx.AsyncClient(
                base_url=request_base_url,
                verify=create_system_ssl_context(),
                timeout=httpx.Timeout(timeout_seconds or self._timeout_seconds),
            )
        try:
            response = await client.get(
                path,
                headers=self._common_headers(),
                timeout=timeout_seconds or self._long_poll_timeout_seconds,
            )
        finally:
            if client is not self._client:
                await client.aclose()
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise WeChatClawBotError("QR status response must be a JSON object")
        return WeChatQrStatus(
            status=str(raw.get("status") or "wait"),
            bot_token=_optional_str(raw.get("bot_token")),
            account_id=_optional_str(raw.get("ilink_bot_id")),
            base_url=_optional_str(raw.get("baseurl")),
            user_id=_optional_str(raw.get("ilink_user_id")),
            redirect_host=_optional_str(raw.get("redirect_host")),
        )

    async def notify_start(self, account: WeChatAccount) -> None:
        raw = await self._post(
            "/ilink/bot/msg/notifystart",
            body={"base_info": self._base_info()},
            token=account.token,
            base_url=account.base_url,
            request_timeout_seconds=self._timeout_seconds,
        )
        ret = raw.get("ret")
        if ret and ret != 0:
            raise WeChatClawBotError(
                f"notifyStart ret={ret} errmsg={raw.get('errmsg') or '(none)'}"
            )

    async def ensure_started(self, account: WeChatAccount) -> None:
        if account.account_id in self._started_accounts:
            return
        await self.notify_start(account)
        self._started_accounts.add(account.account_id)

    async def get_updates(
        self,
        account: WeChatAccount,
        cursor: str,
    ) -> WeChatUpdateBatch:
        await self.ensure_started(account)
        try:
            raw = await self._post(
                "/ilink/bot/getupdates",
                body={
                    "get_updates_buf": cursor,
                    "base_info": self._base_info(),
                },
                token=account.token,
                base_url=account.base_url,
                request_timeout_seconds=self._long_poll_timeout_seconds,
            )
        except httpx.TimeoutException:
            # A client-side long-poll timeout is a normal control-flow exit;
            # the caller retries with the same cursor.
            return WeChatUpdateBatch(cursor=cursor)
        messages = tuple(
            message
            for message in (
                _inbound_message(item) for item in raw.get("msgs") or [] if isinstance(item, dict)
            )
            if message is not None
        )
        return WeChatUpdateBatch(
            messages=messages,
            cursor=str(raw.get("get_updates_buf") or raw.get("sync_buf") or ""),
            ret=int(raw.get("ret") or 0),
            error_code=_optional_int(raw.get("errcode")),
            error_message=_optional_str(raw.get("errmsg")),
            long_poll_timeout_ms=_optional_int(raw.get("longpolling_timeout_ms")),
        )

    async def send_text(
        self,
        account: WeChatAccount,
        *,
        to_user_id: str,
        text: str,
        context_token: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        client_id = (
            f"dota-ai-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]}"
            if idempotency_key
            else f"dota-ai-{uuid4().hex}"
        )
        raw = await self._post(
            "/ilink/bot/sendmessage",
            body={
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": client_id,
                    "message_type": MESSAGE_TYPE_BOT,
                    "message_state": MESSAGE_STATE_FINISH,
                    "item_list": [{"type": ITEM_TYPE_TEXT, "text_item": {"text": text}}],
                    **({"context_token": context_token} if context_token else {}),
                    **({"run_id": run_id} if run_id else {}),
                },
                "base_info": self._base_info(),
            },
            token=account.token,
            base_url=account.base_url,
            request_timeout_seconds=self._timeout_seconds,
        )
        ret = raw.get("ret")
        if ret and ret != 0:
            raise WeChatClawBotError(
                f"sendMessage ret={ret} errmsg={raw.get('errmsg') or '(none)'}"
            )
        return client_id

    async def _post(
        self,
        path: str,
        *,
        body: dict[str, Any],
        token: str | None = None,
        base_url: str | None = None,
        request_timeout_seconds: float,
    ) -> dict[str, Any]:
        request_base_url = (base_url or self._base_url).rstrip("/")
        client = self._client
        if self._owns_client and request_base_url != self._base_url:
            client = httpx.AsyncClient(
                base_url=request_base_url,
                verify=create_system_ssl_context(),
                timeout=httpx.Timeout(request_timeout_seconds),
            )
        try:
            response = await client.post(
                path,
                json=body,
                headers=self._post_headers(token=token),
                timeout=request_timeout_seconds,
            )
        finally:
            if client is not self._client:
                await client.aclose()
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise WeChatClawBotError("WeChat API response must be a JSON object")
        return raw

    def _common_headers(self) -> dict[str, str]:
        return {
            "iLink-App-Id": WECHAT_APP_ID,
            "iLink-App-ClientVersion": CLIENT_VERSION,
        }

    def _post_headers(self, *, token: str | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": _random_wechat_uin(),
            **self._common_headers(),
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _base_info(self) -> dict[str, str]:
        return {
            "channel_version": WECHAT_CHANNEL_VERSION,
            "bot_agent": self._bot_agent,
        }


def _inbound_message(item: dict[str, Any]) -> WeChatInboundMessage | None:
    texts = []
    for entry in item.get("item_list") or []:
        if not isinstance(entry, dict) or entry.get("type") != ITEM_TYPE_TEXT:
            continue
        text_item = entry.get("text_item")
        text = text_item.get("text") if isinstance(text_item, dict) else None
        if isinstance(text, str) and text.strip():
            texts.append(text)
    if not texts:
        return None
    return WeChatInboundMessage(
        message_id=_optional_int(item.get("message_id")),
        from_user_id=_optional_str(item.get("from_user_id")),
        to_user_id=_optional_str(item.get("to_user_id")),
        context_token=_optional_str(item.get("context_token")),
        run_id=_optional_str(item.get("run_id")),
        session_id=_optional_str(item.get("session_id")),
        group_id=_optional_str(item.get("group_id")),
        message_type=_optional_int(item.get("message_type")),
        text="\n".join(texts),
        created_at_ms=_optional_int(item.get("create_time_ms")),
    )


def _random_wechat_uin() -> str:
    value = secrets.randbits(32)
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _sanitize_bot_agent(raw: str) -> str:
    import re

    tokens = []
    for candidate in raw.split():
        match = re.fullmatch(
            r"([A-Za-z0-9_.\-]{1,32}/[A-Za-z0-9_.+\-]{1,32})( \([^()]{1,64}\))?", candidate
        )
        if match:
            tokens.append(match.group(0))
    joined = " ".join(tokens).strip()
    if not joined or len(joined.encode("utf-8")) > 256:
        return "Dota-AI-Decision-Lab/0.1.0"
    return joined


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
