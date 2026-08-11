from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical import content_digest
from app.models import ProviderRawEvent


class RawEventRepository:
    async def append(
        self,
        session: AsyncSession,
        *,
        provider: str,
        event_type: str,
        provider_key: str | None,
        payload: dict[str, Any],
        received_at: datetime,
        parser_version: str,
        request_started_at: datetime | None = None,
        provider_event_at: datetime | None = None,
    ) -> UUID:
        record = ProviderRawEvent(
            provider=provider,
            event_type=event_type,
            provider_key=provider_key,
            request_started_at=request_started_at,
            provider_event_at=provider_event_at,
            received_at=received_at,
            payload=payload,
            payload_hash=content_digest(payload),
            parser_version=parser_version,
        )
        session.add(record)
        await session.flush()
        return record.id
