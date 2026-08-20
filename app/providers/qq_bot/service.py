"""QQ Bot service: inbound commands and durable decision notifications."""

import asyncio
from collections.abc import Sequence
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
from app.providers.qq_bot.bridge_client import QQBridgeClient
from app.providers.qq_bot.models import (
    QQ_SCOPE_C2C,
    QQ_SCOPE_GROUP,
    QQContact,
    QQInboundMessage,
)
from app.providers.qq_bot.storage import QQBotStore
from app.runtime.health import HealthRegistry
from app.time import ensure_utc

logger = structlog.get_logger()


class QQBotService:
    """Dota AI commands and decision push over the harness QQ Bot bridge."""

    def __init__(
        self,
        *,
        client: QQBridgeClient,
        store: QQBotStore,
        session_factory: async_sessionmaker[AsyncSession],
        jobs: JobRepository,
        health: HealthRegistry | None = None,
        configured_targets: Sequence[QQContact] = (),
        allowed_c2c_ids: Sequence[str] = (),
        allowed_group_ids: Sequence[str] = (),
        group_require_mention: bool = True,
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
        self._configured_targets = tuple(configured_targets)
        self._allowed_c2c_ids = frozenset(allowed_c2c_ids)
        self._allowed_group_ids = frozenset(allowed_group_ids)
        self._group_require_mention = group_require_mention
        self._live_state_max_age_seconds = live_state_max_age_seconds
        self._live_market_max_age_seconds = live_market_max_age_seconds
        self._market_max_pair_skew_seconds = market_max_pair_skew_seconds
        self._max_decision_age_seconds = max_decision_age_seconds
        self._stop = asyncio.Event()
        self._inbound_task: asyncio.Task | None = None
        self._closed = False

    @property
    def client(self) -> QQBridgeClient:
        return self._client

    async def create_share_link(self, callback_data: str) -> str:
        """Create an official QQ share link for a user-scoped pairing code."""
        return await self._client.create_share_link(callback_data)

    @property
    def store(self) -> QQBotStore:
        return self._store

    async def prepare_decision_notification(
        self,
        session: AsyncSession,
        *,
        snapshot: DecisionSnapshot,
        decisions: list[AiDecisionRecord],
    ) -> None:
        if not self._decision_targets():
            return
        reason = await self._decision_notification_block_reason(session, snapshot)
        if reason is not None:
            logger.info(
                "qq_bot_decision_suppressed",
                phase="prepare",
                snapshot_id=str(snapshot.snapshot_id),
                reason=reason,
            )
            return
        decision_ids = ",".join(sorted(str(item.id) for item in decisions))
        await self._jobs.enqueue(
            session,
            job_type=JobType.SEND_QQ_DECISION,
            dedupe_key=f"qq-decision:{snapshot.snapshot_id}:{decision_ids}",
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
        targets = self._decision_targets()
        if not targets:
            return 0
        reason = self._decision_age_block_reason(snapshot)
        if reason is None and self._session_factory is not None:
            async with self._session_factory() as session:
                reason = await self._decision_notification_block_reason(
                    session, snapshot, check_age=False
                )
        if reason is not None:
            logger.info(
                "qq_bot_decision_suppressed",
                phase="send",
                snapshot_id=str(snapshot.snapshot_id),
                reason=reason,
            )
            return 0
        text = render_decision_notification(snapshot, decisions, channel_label="QQ")
        decision_batch_key = ",".join(sorted(str(item.id) for item in decisions))
        sent = 0
        for target in targets:
            await self._client.send_text(
                scope=target.scope,
                target_id=target.target_id,
                text=text,
                idempotency_key=(
                    f"qq-decision:{snapshot.snapshot_id}:"
                    f"{decision_batch_key}:{target.scope}:{target.target_id}"
                ),
            )
            sent += 1
        return sent

    async def send_to_target(self, target: QQContact, text: str) -> str:
        return await self._client.send_text(
            scope=target.scope,
            target_id=target.target_id,
            text=text,
        )

    async def run_inbound(self) -> None:
        self._stop.clear()
        backoff = 1.0
        while not self._stop.is_set():
            accounts = list(self._store.accounts())
            if not accounts:
                await self._update_health(
                    "ACTION_REQUIRED",
                    message="run: python -m tools.qq_bot login",
                )
                await self._sleep(15)
                continue
            for account in accounts:
                if self._stop.is_set():
                    break
                try:
                    cursor = self._store.cursor(account.app_id)
                    batch = await self._client.events(cursor)
                    if batch.cursor < cursor:
                        # The bridge buffer is in-memory and may have restarted
                        # since the last poll. Re-read from its new origin so a
                        # newly invited user's FRIEND_ADD event is not skipped.
                        logger.info(
                            "qq_bridge_cursor_reset",
                            account_id=account.app_id,
                            previous_cursor=cursor,
                            bridge_cursor=batch.cursor,
                        )
                        cursor = 0
                        batch = await self._client.events(cursor)
                    async with self._session_factory() as session, session.begin():
                        for message in batch.events:
                            await self._handle_message(session, message)
                    if batch.cursor >= cursor:
                        self._store.save_cursor(account.app_id, batch.cursor)
                    await self._update_health(
                        "READY",
                        messages=len(batch.events),
                        account_id=account.app_id,
                        target_count=len(self._decision_targets()),
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

    def _decision_targets(self) -> list[QQContact]:
        merged: dict[tuple[str, str], QQContact] = {}
        for target in self._configured_targets:
            merged[target.key] = target
        for contact in self._store.subscribed_contacts():
            existing = merged.get(contact.key)
            merged[contact.key] = (
                contact if existing is None else existing.model_copy(update={"subscribed": True})
            )
        return list(merged.values())

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
        message: QQInboundMessage,
    ) -> None:
        if not message.text.strip() or not message.sender_id:
            return
        if not self._message_allowed(message):
            return
        contact = self._record_contact(message)
        normalized = message.text.strip().casefold()
        if normalized in {"订阅通知", "订阅决策", "订阅"}:
            self._store.set_contact_subscribed(message.scope, message.target_id, enabled=True)
            reply = "✅ 已订阅 AI 决策 QQ 通知。发送「退订通知」可取消。"
        elif normalized in {"退订通知", "退订", "取消订阅"}:
            self._store.set_contact_subscribed(message.scope, message.target_id, enabled=False)
            reply = "✅ 已退订 AI 决策 QQ 通知。发送「订阅通知」可重新开启。"
        else:
            reply = await command_reply(
                session,
                self._store,
                message.text,
                channel_label="QQ",
                live_state_max_age_seconds=self._live_state_max_age_seconds,
                live_market_max_age_seconds=self._live_market_max_age_seconds,
                market_max_pair_skew_seconds=self._market_max_pair_skew_seconds,
            )
        await self._client.send_text(
            scope=message.scope,
            target_id=message.target_id,
            text=reply,
            msg_id=message.message_id,
        )
        if message.sender_name and contact.label is None:
            self._store.save_contact(contact.model_copy(update={"label": message.sender_name}))

    def _message_allowed(self, message: QQInboundMessage) -> bool:
        if message.scope == QQ_SCOPE_C2C:
            return not self._allowed_c2c_ids or message.sender_id in self._allowed_c2c_ids
        if message.scope != QQ_SCOPE_GROUP:
            return False
        if self._allowed_group_ids and message.target_id not in self._allowed_group_ids:
            return False
        if self._group_require_mention and not message.bot_mentioned:
            return False
        return True

    def _record_contact(self, message: QQInboundMessage) -> QQContact:
        now = datetime.now(UTC)
        existing = self._store.contact(message.scope, message.target_id)
        subscribed = existing.subscribed if existing is not None else message.scope == QQ_SCOPE_C2C
        contact = existing or QQContact(
            scope=message.scope,  # type: ignore[arg-type]
            target_id=message.target_id,
            subscribed=subscribed,
            first_seen_at=now,
            last_seen_at=now,
        )
        contact = contact.model_copy(update={"last_seen_at": now})
        self._store.save_contact(contact)
        return contact

    async def _update_health(
        self, status: str, *, message: str | None = None, **metadata: Any
    ) -> None:
        if self._health is None:
            return
        await self._health.dependency("QQ", status, message=message, **metadata)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass
