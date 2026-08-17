from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import CanonicalEvent, CanonicalMap, CanonicalSeries, CanonicalTeam
from app.web.quality import build_position_audit

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_position_audit_is_event_scoped_and_preserves_execution_facts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        event = CanonicalEvent(name="Audit Cup", started_at=NOW)
        other_event = CanonicalEvent(name="Other Cup", started_at=NOW)
        team_a = CanonicalTeam(name="Team A")
        team_b = CanonicalTeam(name="Team B")
        session.add_all([event, other_event, team_a, team_b])
        await session.flush()

        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=3,
            scheduled_at=NOW,
        )
        session.add(series)
        await session.flush()
        map_one = CanonicalMap(series_id=series.id, map_number=1, scheduled_at=NOW)
        map_two = CanonicalMap(
            series_id=series.id,
            map_number=2,
            scheduled_at=NOW + timedelta(hours=1),
        )
        session.add_all([map_one, map_two])
        await session.flush()

        account = TournamentPortfolioAccountRecord(
            canonical_event_id=event.id,
            provider="openai",
            model="gpt-fixture",
            prompt_version="prompt-v1",
            decision_policy_version="portfolio-v1",
            ai_view_version="view-v1",
            initial_bankroll=Decimal("10000.00"),
            cash_balance=Decimal("10500.00"),
            locked_balance=Decimal("0.00"),
            realized_pnl=Decimal("500.00"),
            peak_equity=Decimal("10500.00"),
            max_drawdown=Decimal("0.00"),
            max_drawdown_pct=0.0,
            status="ACTIVE",
        )
        session.add(account)
        await session.flush()

        won = TournamentPortfolioPositionRecord(
            portfolio_account_id=account.id,
            ai_decision_id=uuid4(),
            canonical_event_id=event.id,
            canonical_series_id=series.id,
            canonical_map_id=map_one.id,
            action="BUY_A",
            cash_before=Decimal("10000.00"),
            stake=Decimal("500.00"),
            odds=Decimal("2.00000"),
            status="WON",
            payout=Decimal("1000.00"),
            realized_pnl=Decimal("500.00"),
            opened_at=NOW + timedelta(minutes=10),
            settled_at=NOW + timedelta(minutes=50),
        )
        rejected = TournamentPortfolioPositionRecord(
            portfolio_account_id=account.id,
            ai_decision_id=uuid4(),
            canonical_event_id=event.id,
            canonical_series_id=series.id,
            canonical_map_id=map_two.id,
            action="BUY_B",
            cash_before=Decimal("10500.00"),
            stake=Decimal("700.00"),
            odds=None,
            status="REJECTED",
            rejection_reason="MARKET_NOT_EXECUTABLE",
            payout=None,
            realized_pnl=None,
            opened_at=NOW + timedelta(hours=1, minutes=10),
            settled_at=None,
        )
        session.add_all([won, rejected])
        await session.flush()

        payload = await build_position_audit(
            session,
            canonical_event_id=event.id,
            account_id=account.id,
        )
        assert payload is not None
        assert payload["canonical_event_id"] == str(event.id)
        assert payload["experiment"] == {
            "provider": "openai",
            "model": "gpt-fixture",
            "prompt_version": "prompt-v1",
            "decision_policy_version": "portfolio-v1",
            "ai_view_version": "view-v1",
        }
        assert [row["map_number"] for row in payload["positions"]] == [2, 1]
        assert payload["positions"][0]["status"] == "REJECTED"
        assert payload["positions"][0]["selected_team"] == {
            "id": str(team_b.id),
            "name": "Team B",
        }
        assert payload["positions"][0]["rejection_reason"] == "MARKET_NOT_EXECUTABLE"
        assert payload["positions"][0]["cash_before"] == 10500.0
        assert payload["positions"][1]["status"] == "WON"
        assert payload["positions"][1]["selected_team"] == {
            "id": str(team_a.id),
            "name": "Team A",
        }
        assert payload["positions"][1]["odds"] == 2.0
        assert payload["positions"][1]["stake"] == 500.0
        assert payload["positions"][1]["payout"] == 1000.0
        assert payload["positions"][1]["realized_pnl"] == 500.0

        assert (
            await build_position_audit(
                session,
                canonical_event_id=other_event.id,
                account_id=account.id,
            )
            is None
        )

    await engine.dispose()
