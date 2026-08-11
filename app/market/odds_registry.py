from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market import OddsMeta
from app.models import RayBetOddsRegistry


class OddsRegistry:
    async def replace_match_metadata(
        self,
        session: AsyncSession,
        *,
        metadata: list[OddsMeta],
        raw_event_id,
        refreshed_at: datetime,
    ) -> None:
        for item in metadata:
            await session.merge(
                RayBetOddsRegistry(
                    odds_id=item.odds_id,
                    provider_match_id=item.match_id,
                    team_id=item.team_id,
                    team_name=item.team_name,
                    group_short_name=item.group_short_name,
                    match_stage=item.match_stage,
                    raw_status=item.raw_status,
                    refreshed_at=refreshed_at,
                    raw_event_id=raw_event_id,
                )
            )

    async def get(self, session: AsyncSession, odds_id: int) -> RayBetOddsRegistry | None:
        return await session.get(RayBetOddsRegistry, odds_id)
