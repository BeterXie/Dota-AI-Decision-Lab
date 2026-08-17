from app.domain.jobs import JobType
from app.notifications.center import (
    CHANNEL_QQ,
    NotificationBindingConflict,
    NotificationCenterService,
    NotificationPairingError,
    qq_destination_key,
)
from app.providers.chat_commands import render_decision_notification
from app.providers.qq_bot.models import QQInboundMessage
from app.providers.qq_bot.service import QQBotService as LegacyQQBotService


class UserScopedQQBotService(LegacyQQBotService):
    """QQ transport backed by verified user Notification Center bindings."""

    def __init__(self, *args, session_factory, **kwargs) -> None:
        super().__init__(*args, session_factory=session_factory, **kwargs)
        self._notification_center = NotificationCenterService(session_factory)

    async def prepare_decision_notification(self, session, *, snapshot, decisions) -> None:
        reason = await self._decision_notification_block_reason(session, snapshot)
        if reason is not None:
            return
        decision_ids = [item.id for item in decisions]
        deliveries = await self._notification_center.ensure_deliveries(
            session,
            channel=CHANNEL_QQ,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=decision_ids,
        )
        if not deliveries:
            return
        batch = ",".join(sorted(str(item) for item in decision_ids))
        await self._jobs.enqueue(
            session,
            job_type=JobType.SEND_QQ_DECISION,
            dedupe_key=f"user-qq-decision:{snapshot.snapshot_id}:{batch}",
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "decision_ids": [str(item) for item in decision_ids],
            },
            priority=50,
            max_attempts=6,
        )

    async def send_decision_notification(self, *, snapshot, decisions) -> int:
        decision_ids = [item.id for item in decisions]
        delivery_ids = await self._notification_center.batch_delivery_ids(
            channel=CHANNEL_QQ,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=decision_ids,
        )
        if not delivery_ids:
            return 0
        reason = self._decision_age_block_reason(snapshot)
        if reason is None:
            async with self._session_factory() as session:
                reason = await self._decision_notification_block_reason(
                    session,
                    snapshot,
                    check_age=False,
                )
        if reason is not None:
            for delivery_id in delivery_ids:
                await self._notification_center.mark_expired(delivery_id, reason)
            return 0

        text = render_decision_notification(snapshot, decisions, channel_label="QQ")
        sent = 0
        for delivery_id in delivery_ids:
            target = await self._notification_center.start_delivery(delivery_id)
            if target is None:
                continue
            scope = target.destination.get("scope")
            target_id = target.destination.get("target_id")
            if scope not in {"c2c", "group"} or not isinstance(target_id, str) or not target_id:
                exc = ValueError("QQ notification binding is invalid")
                await self._notification_center.mark_failed(delivery_id, exc)
                raise exc
            try:
                provider_message_id = await self._client.send_text(
                    scope=scope,
                    target_id=target_id,
                    text=text,
                    idempotency_key=target.idempotency_key,
                )
            except Exception as exc:
                await self._notification_center.mark_failed(delivery_id, exc)
                raise
            await self._notification_center.mark_sent(delivery_id, provider_message_id)
            sent += 1
        return sent

    async def _handle_message(self, session, message: QQInboundMessage) -> None:
        if not message.text.strip() or not message.sender_id or not self._message_allowed(message):
            return
        normalized = message.text.strip().casefold()
        destination_key = qq_destination_key(message.scope, message.target_id)
        pairing_code = _pairing_code_from_text(message.text)
        if pairing_code is not None:
            contact = self._record_contact(message)
            try:
                await self._notification_center.consume_pairing_code(
                    channel=CHANNEL_QQ,
                    code=pairing_code,
                    destination_key=destination_key,
                    destination={"scope": message.scope, "target_id": message.target_id},
                    label=message.sender_name or contact.label,
                )
                reply = "✅ QQ 已绑定到你的 Notification Center，AI 决策实时通知已开启。"
            except NotificationBindingConflict:
                reply = "⚠️ 这个 QQ 会话已经绑定到另一个账号。请先在原账号里解除绑定。"
            except NotificationPairingError:
                reply = "⚠️ 配对码无效或已过期。请回到 Notification Center 重新生成。"
            await self._client.send_text(
                scope=message.scope,
                target_id=message.target_id,
                text=reply,
                msg_id=message.message_id,
            )
            return

        if normalized in {"订阅通知", "订阅决策", "订阅"}:
            updated = await self._notification_center.set_preference_for_destination(
                channel=CHANNEL_QQ,
                destination_key=destination_key,
                enabled=True,
            )
            reply = (
                "✅ 已开启 AI 决策 QQ 通知。"
                if updated
                else "请先在网页 Notification Center 生成配对码，再发送「绑定 <配对码>」。"
            )
            await self._client.send_text(
                scope=message.scope,
                target_id=message.target_id,
                text=reply,
                msg_id=message.message_id,
            )
            return
        if normalized in {"退订通知", "退订", "取消订阅"}:
            updated = await self._notification_center.set_preference_for_destination(
                channel=CHANNEL_QQ,
                destination_key=destination_key,
                enabled=False,
            )
            reply = "✅ 已关闭 AI 决策 QQ 通知。" if updated else "当前 QQ 会话尚未绑定账号。"
            await self._client.send_text(
                scope=message.scope,
                target_id=message.target_id,
                text=reply,
                msg_id=message.message_id,
            )
            return
        await super()._handle_message(session, message)


def _pairing_code_from_text(text: str) -> str | None:
    value = text.strip()
    folded = value.casefold()
    for prefix in ("绑定 ", "绑定通知 ", "bind ", "/bind "):
        if folded.startswith(prefix.casefold()):
            code = value[len(prefix) :].strip()
            return code or None
    return None
