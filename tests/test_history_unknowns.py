from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.history.service import HistoricalIntelligenceService


@pytest.mark.asyncio
async def test_missing_team_history_remains_unknown() -> None:
    session = AsyncMock()
    session.scalar.side_effect = [None, None]

    payload = await HistoricalIntelligenceService().get_team_payload(
        session, uuid4(), as_of=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert payload["base_rating"] is None
    assert payload["recent_form"] is None
    assert payload["exact_roster_maps"] is None
    assert payload["knowledge_cutoff"] is None


@pytest.mark.asyncio
async def test_missing_player_history_has_unknown_confidence() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    service = HistoricalIntelligenceService()

    player = await service.get_player_payload(
        session, uuid4(), position=1, as_of=datetime(2026, 1, 1, tzinfo=UTC)
    )
    player_hero = await service.get_player_hero_payload(
        session,
        uuid4(),
        hero_id=1,
        position=1,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert player["confidence"] is None
    assert player_hero["confidence"] is None
