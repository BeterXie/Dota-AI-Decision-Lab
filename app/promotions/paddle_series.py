from __future__ import annotations

from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.paddle import PaddleCheckout
from app.promotions.paddle_pass import (
    CompetitionPassCheckoutConflict,
    CompetitionPassWebhookResult,
    PaddleCompetitionPassService,
)


class PaddleSeriesPassService(PaddleCompetitionPassService):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        api_key: str,
        webhook_secret: str,
        api_base_url: str,
        price_id: str,
        checkout_url: str | None = None,
        api_timeout_seconds: float = 15.0,
        webhook_tolerance_seconds: int = 5,
    ) -> None:
        super().__init__(
            session_factory,
            scope_type="SERIES",
            api_key=api_key,
            webhook_secret=webhook_secret,
            api_base_url=api_base_url,
            price_id=price_id,
            checkout_url=checkout_url,
            api_timeout_seconds=api_timeout_seconds,
            webhook_tolerance_seconds=webhook_tolerance_seconds,
        )

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        canonical_series_id: UUID,
        client: httpx.AsyncClient | None = None,
    ) -> PaddleCheckout:
        return await super().create_checkout(
            user_id=user_id,
            email=email,
            target_id=canonical_series_id,
            client=client,
        )


SeriesPassCheckoutConflict = CompetitionPassCheckoutConflict
SeriesPassWebhookResult = CompetitionPassWebhookResult
