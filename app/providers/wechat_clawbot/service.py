import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.jobs import JobType
from app.domain.snapshot import DecisionSnapshot
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DecisionSnapshotRecord, MapResultRecord
from app.providers.chat_commands import command_reply, render_decision_notification
from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.models import (
    MESSAGE_TYPE_USER,
    WeChatAccount,
    WeChatInboundMessage,
)
from app.providers.wechat_clawbot.storage import WeChatClawBotStore
from app.runtime.health import HealthRegistry
from app.time import ensure_utc

logger = structlog.get_logger()


class WeChatClawBotService:
    """Official WeChat ClawBot channel wired directly into the harness.

    No OpenClaw runtime is involved: the service talks to Tencent's iLink bot
    HTTP API, persists the QR-confirmed credentials locally, long-polls inbound
    direct chats, and pushes decision notifications.
    """

    def __init__(
        self,
        *,
        client: WeChatClawBotClient,
        store: WeChatClawBotStore,
        session_factory: async_sessionmaker[AsyncSession],
        jobs: JobRepository,
        health: HealthRegistry | None = None,
        live_state_max_age_seconds: float = 120.0,
        live_market_max_age_seconds: float = 90.0,
        market_max_pair_skew_seconds: float = 5.0,
        max_decision_age_seconds: float = 600.0,
    ) -> None:
        self._client = client
        self._store = store
        self._session_factory = session_factory
        self._jobs = jobs
        self._health = health
        self._live_state_max_age_seconds = live_state_max_age_seconds
        self._live_market_max_age_seconds = live_market_max_age_seconds
        self._market_max_pair_skew_seconds = market_max_pair_skew_seconds
        self._max_decision_age_seconds = max_decision_age_seconds
        self._stop = asyncio.Event()
        self._inbound_task: asyncio.Task | None = None
        self._closed = False

    @property
    def client(self) -> WeChatClawBotClient:
        return self._client

    @property
    def store(self) -> WeChatClawBotStore:
        return self._store

    async def prepare_decision_notification(
        self,
        session: AsyncSession,
        *,
        snapshot: DecisionSnapshot,
        decisions: list[AiDecisionRecord],
    ) -> None:
        if not self._store.accounts():
            return
        reason = await self._decision_notification_block_reason(session, snapshot)
        if reason is not None:
            logger.info(
                "wechat_clawbot_decision_suppressed",
                phase="prepare",
                snapshot_id=str(snapshot.snapshot_id),
                reason=reason,
            )
            return
        decision_ids = ",".join(sorted(str(item.id) for item in decisions))
        await self._jobs.enqueue(
            session,
            job_type=JobType.SEND_WECHAT_DECISION,
            dedupe_key=f"wechat-decision:{snapshot.snapshot_id}:{decision_ids}",
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "decision_ids": [str(item.id) for item in decisions],
            },
            priority=50,
            max_attempts=6,
        )

    async def send_decision_notification(
        self,
        *,
        snapshot: DecisionSnapshot,
        decisions: list[AiDecisionRecord],
    ) -> int:
        if not self._store.decision_notifications_enabled():
            return 0
        accounts = list(self._store.accounts())
        if not accounts:
            return 0
        reason = self._decision_age_block_reason(snapshot)
        if reason is None and self._session_factory is not None:
            async with self._session_factory() as session:
                reason = await self._decision_notification_block_reason(
                    session, snapshot, check_age=False
                )
        if reason is not None:
            logger.info(
                "wechat_clawbot_decision_suppressed",
                phase="send",
                snapshot_id=str(snapshot.snapshot_id),
                reason=reason,
            )
            return 0
        text = render_decision_notification(snapshot, decisions, channel_label="微信")
        decision_batch_key = ",".join(sorted(str(item.id) for item in decisions))
        sent = 0
        for account in accounts:
            if not account.user_id:
                continue
            await self._client.send_text(
                account,
                to_user_id=account.user_id,
                text=text,
                context_token=account.context_token,
                idempotency_key=(
                    f"wechat-decision:{snapshot.snapshot_id}:"
                    f"{decision_batch_key}:{account.account_id}"
                ),
            )
            sent += 1
        return sent

    async def send_to_account(self, account: WeChatAccount, text: str) -> str:
        if not account.user_id:
            raise ValueError("WeChat account has no bound user id yet")
        return await self._client.send_text(
            account,
            to_user_id=account.user_id,
            text=text,
            context_token=account.context_token,
        )

    async def run_inbound(self) -> None:
        self._stop.clear()
        backoff = 1.0
        while not self._stop.is_set():
            accounts = list(self._store.accounts())
            if not accounts:
                await self._update_health(
                    "ACTION_REQUIRED", message="no bound WeChat ClawBot account"
                )
                await self._sleep(15)
                continue
            for account in accounts:
                if self._stop.is_set():
                    break
                try:
                    cursor = self._store.cursor(account.account_id)
                    batch = await self._client.get_updates(account, cursor)
                    logger.debug(
                        "wechat_clawbot_poll",
                        account_id=account.account_id,
                        cursor_len=len(cursor),
                        messages=len(batch.messages),
                        error_code=batch.error_code,
                    )
                    if batch.error_code in {None, 0}:
                        if batch.cursor:
                            self._store.save_cursor(account.account_id, batch.cursor)
                        async with self._session_factory() as session, session.begin():
                            for message in batch.messages:
                                if message.message_type != MESSAGE_TYPE_USER:
                                    continue
                                await self._handle_message(session, account, message)
                    await self._update_health(
                        "READY",
                        messages=len(batch.messages),
                        account_id=account.account_id,
                    )
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self._update_health("DEGRADED", message=f"{type(exc).__name__}: {exc}")
                    await self._sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    if self._stop.is_set():
                        break
            await self._sleep(0.5)

    def start_inbound(self) -> asyncio.Task:
        if self._inbound_task is None or self._inbound_task.done():
            self._inbound_task = asyncio.create_task(self.run_inbound())
        return self._inbound_task

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._inbound_task is not None:
            self._inbound_task.cancel()
            try:
                await self._inbound_task
            except asyncio.CancelledError:
                pass
        await self._client.close()

    def _decision_age_block_reason(self, snapshot: DecisionSnapshot) -> str | None:
        age = (datetime.now(UTC) - ensure_utc(snapshot.decision_at)).total_seconds()
        if age > self._max_decision_age_seconds:
            return f"stale_snapshot:{age:.0f}s>{self._max_decision_age_seconds:.0f}s"
        return None

    async def _decision_notification_block_reason(
        self,
        session: AsyncSession,
        snapshot: DecisionSnapshot,
        *,
        check_age: bool = True,
    ) -> str | None:
        if check_age:
            reason = self._decision_age_block_reason(snapshot)
            if reason is not None:
                return reason
        snapshot_record = await session.get(DecisionSnapshotRecord, snapshot.snapshot_id)
        if snapshot_record is None or snapshot_record.canonical_map_id is None:
            return None
        result_id = await session.scalar(
            select(MapResultRecord.id)
            .where(MapResultRecord.canonical_map_id == snapshot_record.canonical_map_id)
            .limit(1)
        )
        return "map_result_available" if result_id is not None else None

    async def _handle_message(
        self,
        session: AsyncSession,
        account: WeChatAccount,
        message: WeChatInboundMessage,
    ) -> None:
        if not message.from_user_id:
            return
        if account.user_id is not None and message.from_user_id != account.user_id:
            logger.warning(
                "wechat_clawbot_unauthorized_sender",
                account_id=account.account_id,
            )
            return
        reply = await command_reply(
            session,
            self._store,
            message.text,
            channel_label="微信",
            live_state_max_age_seconds=self._live_state_max_age_seconds,
            live_market_max_age_seconds=self._live_market_max_age_seconds,
            market_max_pair_skew_seconds=self._market_max_pair_skew_seconds,
        )
        await self._client.send_text(
            account,
            to_user_id=message.from_user_id,
            text=reply,
            context_token=message.context_token,
            run_id=message.run_id,
        )
        updates: dict[str, object] = {}
        if not account.user_id:
            updates["user_id"] = message.from_user_id
        if message.context_token and message.context_token != account.context_token:
            updates["context_token"] = message.context_token
        if updates:
            self._store.save_account(account.model_copy(update=updates))

    async def _update_health(
        self, status: str, *, message: str | None = None, **metadata: Any
    ) -> None:
        if self._health is None:
            return
        await self._health.dependency("WECHAT", status, message=message, **metadata)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass
