from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.domain.jobs import JobType
from app.models import AiDecisionRecord
from app.notifications.center import CHANNEL_EMAIL, NotificationCenterService
from app.notifications.email import DecisionEmailNotificationService, render_decision_email
from app.snapshots.repository import SnapshotRepository


@dataclass(frozen=True, slots=True)
class UserEmailDeliveryReceipt:
    id: UUID
    recipients: tuple[str, ...]
    sent_at: datetime | None


class UserDecisionEmailNotificationService(DecisionEmailNotificationService):
    """User-scoped replacement for the legacy configured-recipient broadcaster.

    The constructor intentionally preserves the legacy signature so runtime
    wiring and direct unit tests can coexist while product delivery moves to
    verified Notification Center bindings.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._notification_center = NotificationCenterService(self._session_factory)

    async def prepare(self, session, *, snapshot, decisions):
        age = (datetime.now(UTC) - _as_utc(snapshot.decision_at)).total_seconds()
        if age > self._max_decision_age_seconds:
            return None
        decision_ids = [item.id for item in decisions]
        deliveries = await self._notification_center.ensure_deliveries(
            session,
            channel=CHANNEL_EMAIL,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=decision_ids,
        )
        for delivery in deliveries:
            if delivery.status in {"SENT", "EXPIRED", "CANCELLED"}:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.SEND_DECISION_EMAIL,
                dedupe_key=f"user-decision-email:{delivery.id}",
                payload={"notification_id": str(delivery.id)},
                priority=50,
                max_attempts=6,
            )
        return deliveries[0].id if deliveries else None

    async def deliver(self, notification_id: UUID) -> UserEmailDeliveryReceipt:
        target = await self._notification_center.start_delivery(notification_id)
        if target is None:
            delivery, destination = await self._notification_center.delivery_receipt(
                notification_id
            )
            email = destination.get("email")
            recipients = (email,) if isinstance(email, str) and email else ()
            return UserEmailDeliveryReceipt(delivery.id, recipients, delivery.sent_at)

        email = target.destination.get("email")
        if not isinstance(email, str) or not email:
            exc = ValueError("email notification binding is missing the verified email")
            await self._notification_center.mark_failed(notification_id, exc)
            raise exc

        async with self._session_factory() as session:
            snapshot = await SnapshotRepository().get(session, target.snapshot_id)
            if snapshot is None:
                exc = ValueError("decision snapshot does not exist")
                await self._notification_center.mark_failed(notification_id, exc)
                raise exc
            age = (datetime.now(UTC) - _as_utc(snapshot.decision_at)).total_seconds()
            if age > self._max_decision_age_seconds:
                await self._notification_center.mark_expired(
                    notification_id,
                    f"Decision snapshot is stale ({age:.0f}s > {self._max_decision_age_seconds:.0f}s)",
                )
                return UserEmailDeliveryReceipt(notification_id, (email,), None)
            decisions = list(
                (
                    await session.scalars(
                        select(AiDecisionRecord).where(AiDecisionRecord.id.in_(target.decision_ids))
                    )
                ).all()
            )
        if len(decisions) != len(target.decision_ids):
            exc = ValueError("email notification references missing AI decisions")
            await self._notification_center.mark_failed(notification_id, exc)
            raise exc

        subject, text_body, html_body = render_decision_email(
            snapshot,
            decisions,
            subject_prefix=self._subject_prefix,
        )
        message = self._message(
            email=email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            idempotency_key=target.idempotency_key,
        )
        try:
            provider_message_id = await self._sender.send(message)
        except Exception as exc:
            await self._notification_center.mark_failed(notification_id, exc)
            raise
        await self._notification_center.mark_sent(notification_id, provider_message_id)
        delivery, _ = await self._notification_center.delivery_receipt(notification_id)
        return UserEmailDeliveryReceipt(delivery.id, (email,), delivery.sent_at)

    def _message(
        self,
        *,
        email: str,
        subject: str,
        text_body: str,
        html_body: str,
        idempotency_key: str,
    ):
        from app.notifications.email import OutgoingEmail

        return OutgoingEmail(
            sender=self._sender_from,
            recipients=(email,),
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            idempotency_key=idempotency_key,
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
