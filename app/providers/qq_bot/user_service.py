from app.domain.jobs import JobType
from app.entitlements import AI_DECISIONS_ENTITLEMENT, EntitlementService
from app.notifications.center import (
    CHANNEL_QQ,
    NotificationBindingConflict,
    NotificationPairingError,
    qq_destination_key,
)
from app.notifications.pairing_limiter import PairingAttemptLimiter
from app.notifications.secure_center import NotificationCenterService
from app.providers.chat_access import (
    is_ai_decision_query,
    is_notification_pause_command,
    is_notification_resume_command,
)
from app.providers.chat_commands import command_reply, render_decision_notification
from app.providers.qq_bot.models import QQContact, QQInboundMessage
from app.providers.qq_bot.service import QQBotService as LegacyQQBotService

_SUBSCRIBE_COMMANDS = {"订阅通知", "订阅决策", "订阅"}
_UNSUBSCRIBE_COMMANDS = {"退订通知", "退订", "取消订阅"}


class UserScopedQQBotService(LegacyQQBotService):
    """QQ transport backed by verified user Notification Center bindings."""

    def __init__(self, *args, session_factory, **kwargs) -> None:
        super().__init__(*args, session_factory=session_factory, **kwargs)
        self._notification_center = NotificationCenterService(session_factory)
        self._entitlements = EntitlementService(session_factory)
        self._pairing_attempts = PairingAttemptLimiter()

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
        # Verified private-chat bindings are represented by Notification Center
        # deliveries. Explicit operator targets and opted-in groups remain
        # transport-local targets and must also wake the durable worker.
        if not deliveries and not self._direct_decision_targets():
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
        direct_targets = self._direct_decision_targets()
        if not delivery_ids and not direct_targets:
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
        failures: list[Exception] = []
        delivery_target_keys: set[tuple[str, str]] = set()
        for delivery_id in delivery_ids:
            target = await self._notification_center.start_delivery(delivery_id)
            if target is None:
                continue
            scope = target.destination.get("scope")
            target_id = target.destination.get("target_id")
            if scope not in {"c2c", "group"} or not isinstance(target_id, str) or not target_id:
                await self._notification_center.mark_expired(
                    delivery_id,
                    "QQ notification binding is no longer backed by a valid target",
                )
                continue
            delivery_target_keys.add((scope, target_id))
            try:
                provider_message_id = await self._client.send_text(
                    scope=scope,
                    target_id=target_id,
                    text=text,
                    idempotency_key=target.idempotency_key,
                )
            except Exception as exc:
                await self._notification_center.mark_failed(delivery_id, exc)
                failures.append(exc)
                continue
            await self._notification_center.mark_sent(delivery_id, provider_message_id)
            sent += 1
        decision_batch_key = ",".join(sorted(str(item.id) for item in decisions))
        for target in direct_targets:
            if target.key in delivery_target_keys:
                continue
            try:
                await self._client.send_text(
                    scope=target.scope,
                    target_id=target.target_id,
                    text=text,
                    idempotency_key=(
                        f"qq-decision:{snapshot.snapshot_id}:{decision_batch_key}:"
                        f"{target.scope}:{target.target_id}"
                    ),
                )
            except Exception as exc:
                failures.append(exc)
                continue
            sent += 1
        if failures:
            first = failures[0]
            raise RuntimeError(
                f"{len(failures)} QQ notification delivery target(s) failed; "
                f"first={type(first).__name__}: {first}"
            ) from first
        return sent

    def _direct_decision_targets(self) -> tuple[QQContact, ...]:
        """Return explicit targets and subscribed groups for direct delivery."""
        merged = {target.key: target for target in self._configured_targets}
        subscribed_contacts = getattr(self._store, "subscribed_contacts", None)
        if callable(subscribed_contacts):
            for contact in subscribed_contacts():
                # Private-chat recipients remain entitlement-scoped through
                # Notification Center. Groups have no account binding and use
                # the channel-local subscription state instead.
                if contact.scope == "group":
                    merged.setdefault(contact.key, contact)
        return tuple(merged.values())

    async def _handle_message(self, session, message: QQInboundMessage) -> None:
        if not message.text.strip() or not message.sender_id or not self._message_allowed(message):
            return
        normalized = message.text.strip().casefold()
        destination_key = qq_destination_key(message.scope, message.target_id)
        pairing_code = _pairing_code_from_text(message.text)
        preference_command = (
            normalized in _SUBSCRIBE_COMMANDS
            or normalized in _UNSUBSCRIBE_COMMANDS
            or is_notification_pause_command(message.text)
            or is_notification_resume_command(message.text)
        )
        premium_query = is_ai_decision_query(message.text)
        group = message.scope == "group"
        group_subscription_command = (
            normalized in _SUBSCRIBE_COMMANDS or normalized in _UNSUBSCRIBE_COMMANDS
        )
        account_command = pairing_code is not None or preference_command or premium_query
        # Groups may opt in/out locally. Binding, premium queries, and
        # per-user pause/resume remain private-chat operations.
        if group and group_subscription_command:
            await super()._handle_message(session, message)
            return
        if group and account_command:
            await self._client.send_text(
                scope=message.scope,
                target_id=message.target_id,
                text=(
                    "⚠️ AI 决策查询、账号绑定和暂停/恢复通知仅支持已绑定的 QQ 私聊。"
                    "群聊请使用「订阅通知」或「退订通知」。"
                ),
                msg_id=message.message_id,
            )
            return

        if pairing_code is not None:
            contact = self._record_contact(message)
            if not self._pairing_attempts.allow(destination_key):
                reply = "⚠️ 配对尝试过于频繁，请稍后重新生成配对码再试。"
            else:
                try:
                    await self._notification_center.consume_pairing_code(
                        channel=CHANNEL_QQ,
                        code=pairing_code,
                        destination_key=destination_key,
                        destination={"scope": "c2c", "target_id": message.target_id},
                        label=message.sender_name or contact.label,
                    )
                    reply = (
                        "✅ QQ 已绑定到你的 Notification Center，AI 决策通知偏好已开启。"
                        "实际推送仍取决于实时通知权限。"
                    )
                except NotificationBindingConflict:
                    reply = "⚠️ 这个 QQ 私聊已经绑定到另一个账号。请先在原账号里解除绑定。"
                except NotificationPairingError:
                    reply = "⚠️ 配对码无效或已过期。请回到 Notification Center 重新生成。"
            await self._client.send_text(
                scope="c2c",
                target_id=message.target_id,
                text=reply,
                msg_id=message.message_id,
            )
            return

        if normalized in _SUBSCRIBE_COMMANDS or is_notification_resume_command(message.text):
            updated = await self._notification_center.set_preference_for_destination(
                channel=CHANNEL_QQ,
                destination_key=destination_key,
                enabled=True,
            )
            reply = (
                "✅ 已开启 AI 决策 QQ 通知。"
                if updated
                else "请先在网页 Notification Center 生成配对码，再私聊发送「绑定 <配对码>」。"
            )
            await self._client.send_text(
                scope="c2c",
                target_id=message.target_id,
                text=reply,
                msg_id=message.message_id,
            )
            return
        if normalized in _UNSUBSCRIBE_COMMANDS or is_notification_pause_command(message.text):
            updated = await self._notification_center.set_preference_for_destination(
                channel=CHANNEL_QQ,
                destination_key=destination_key,
                enabled=False,
            )
            reply = "✅ 已关闭 AI 决策 QQ 通知。" if updated else "当前 QQ 私聊尚未绑定账号。"
            await self._client.send_text(
                scope="c2c",
                target_id=message.target_id,
                text=reply,
                msg_id=message.message_id,
            )
            return
        if premium_query:
            user_id = await self._notification_center.bound_active_user_id(
                channel=CHANNEL_QQ,
                destination_key=destination_key,
            )
            if user_id is None:
                reply = (
                    "🔒 AI 决策查询需要先绑定登录账号。请在网页 Notification Center "
                    "生成配对码，再私聊发送「绑定 <配对码>」。"
                )
            elif not await self._entitlements.has_entitlement(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
            ):
                reply = "🔒 当前账号没有 AI 决策权限。请先开通相应权限后再查询。"
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
                scope="c2c",
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
