from app.domain.jobs import JobType
from app.entitlements import AI_DECISIONS_ENTITLEMENT, EntitlementService
from app.notifications.center import (
    CHANNEL_WECHAT,
    NotificationBindingConflict,
    NotificationPairingError,
    wechat_destination_key,
)
from app.notifications.pairing_limiter import PairingAttemptLimiter
from app.notifications.secure_center import NotificationCenterService
from app.providers.chat_access import (
    is_ai_decision_query,
    is_notification_pause_command,
    is_notification_resume_command,
)
from app.providers.chat_commands import command_reply, render_decision_notification
from app.providers.wechat_clawbot.models import (
    MESSAGE_TYPE_USER,
    WeChatAccount,
    WeChatInboundMessage,
)
from app.providers.wechat_clawbot.service import WeChatClawBotService as LegacyWeChatClawBotService


class UserScopedWeChatClawBotService(LegacyWeChatClawBotService):
    """WeChat transport backed by verified user Notification Center bindings."""

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
            channel=CHANNEL_WECHAT,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=decision_ids,
        )
        if not deliveries:
            return
        batch = ",".join(sorted(str(item) for item in decision_ids))
        await self._jobs.enqueue(
            session,
            job_type=JobType.SEND_WECHAT_DECISION,
            dedupe_key=f"user-wechat-decision:{snapshot.snapshot_id}:{batch}",
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
            channel=CHANNEL_WECHAT,
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

        text = render_decision_notification(snapshot, decisions, channel_label="微信")
        sent = 0
        failures: list[Exception] = []
        accounts = {item.account_id: item for item in self._store.accounts()}
        for delivery_id in delivery_ids:
            target = await self._notification_center.start_delivery(delivery_id)
            if target is None:
                continue
            account_id = target.destination.get("account_id")
            user_id = target.destination.get("user_id")
            account = accounts.get(account_id) if isinstance(account_id, str) else None
            if account is None or not isinstance(user_id, str) or not user_id:
                await self._notification_center.mark_expired(
                    delivery_id,
                    "WeChat notification binding is no longer backed by a bot account",
                )
                continue
            try:
                provider_message_id = await self._client.send_text(
                    account,
                    to_user_id=user_id,
                    text=text,
                    context_token=account.context_token,
                    idempotency_key=target.idempotency_key,
                )
            except Exception as exc:
                await self._notification_center.mark_failed(delivery_id, exc)
                failures.append(exc)
                continue
            await self._notification_center.mark_sent(delivery_id, provider_message_id)
            sent += 1
        if failures:
            first = failures[0]
            raise RuntimeError(
                f"{len(failures)} WeChat notification delivery target(s) failed; "
                f"first={type(first).__name__}: {first}"
            ) from first
        return sent

    async def _handle_message(
        self,
        session,
        account: WeChatAccount,
        message: WeChatInboundMessage,
    ) -> None:
        if (
            message.message_type != MESSAGE_TYPE_USER
            or not message.from_user_id
            or message.group_id is not None
        ):
            return
        bound_user_id = account.user_id
        # A QR account is not allowed to execute commands on behalf of an
        # arbitrary sender. Pairing is the sole operation permitted while the
        # account is unbound; once bound, every direct message must match it.
        if bound_user_id and message.from_user_id != bound_user_id:
            return
        destination_key = wechat_destination_key(account.account_id, message.from_user_id)
        normalized = message.text.strip().casefold()
        pairing_code = _pairing_code_from_text(message.text)
        if pairing_code is not None:
            if not self._pairing_attempts.allow(destination_key):
                reply = "⚠️ 配对尝试过于频繁，请稍后重新生成配对码再试。"
            else:
                try:
                    await self._notification_center.consume_pairing_code(
                        channel=CHANNEL_WECHAT,
                        code=pairing_code,
                        destination_key=destination_key,
                        destination={
                            "account_id": account.account_id,
                            "user_id": message.from_user_id,
                        },
                        label=message.from_user_id,
                    )
                    reply = (
                        "✅ 微信已绑定到你的 Notification Center，AI 决策通知偏好已开启。"
                        "实际推送仍取决于实时通知权限。"
                    )
                    self._persist_account_binding(
                        account,
                        user_id=message.from_user_id,
                        context_token=message.context_token,
                    )
                except NotificationBindingConflict:
                    reply = "⚠️ 这个微信会话已经绑定到另一个账号。请先在原账号里解除绑定。"
                except NotificationPairingError:
                    reply = "⚠️ 配对码无效或已过期。请回到 Notification Center 重新生成。"
        elif not bound_user_id:
            reply = (
                "🔒 当前微信会话需要先绑定登录账号。请在网页 Notification Center "
                "生成配对码，再发送「绑定 <配对码>」。"
            )
        elif normalized in {"订阅通知", "订阅决策", "订阅"} or is_notification_resume_command(
            message.text
        ):
            updated = await self._notification_center.set_preference_for_destination(
                channel=CHANNEL_WECHAT,
                destination_key=destination_key,
                enabled=True,
            )
            reply = (
                "✅ 已开启 AI 决策微信通知。"
                if updated
                else "请先在网页 Notification Center 生成配对码，再发送「绑定 <配对码>」。"
            )
        elif normalized in {"退订通知", "退订", "取消订阅"} or is_notification_pause_command(
            message.text
        ):
            updated = await self._notification_center.set_preference_for_destination(
                channel=CHANNEL_WECHAT,
                destination_key=destination_key,
                enabled=False,
            )
            reply = "✅ 已关闭 AI 决策微信通知。" if updated else "当前微信会话尚未绑定账号。"
        elif is_ai_decision_query(message.text):
            user_id = await self._notification_center.bound_active_user_id(
                channel=CHANNEL_WECHAT,
                destination_key=destination_key,
            )
            if user_id is None:
                reply = (
                    "🔒 AI 决策查询需要先绑定登录账号。请在网页 Notification Center "
                    "生成配对码，再发送「绑定 <配对码>」。"
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
                    channel_label="微信",
                    live_state_max_age_seconds=self._live_state_max_age_seconds,
                    live_market_max_age_seconds=self._live_market_max_age_seconds,
                    market_max_pair_skew_seconds=self._market_max_pair_skew_seconds,
                )
        else:
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

    def _persist_account_binding(
        self,
        account: WeChatAccount,
        *,
        user_id: str,
        context_token: str | None,
    ) -> None:
        """Persist the sender identity after a successful pairing handshake."""
        updates: dict[str, object] = {"user_id": user_id}
        if context_token:
            updates["context_token"] = context_token
        self._store.save_account(account.model_copy(update=updates))


def _pairing_code_from_text(text: str) -> str | None:
    value = text.strip()
    folded = value.casefold()
    for prefix in ("绑定 ", "绑定通知 ", "bind ", "/bind "):
        if folded.startswith(prefix.casefold()):
            code = value[len(prefix) :].strip()
            return code or None
    return None
