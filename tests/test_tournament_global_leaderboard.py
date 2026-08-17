from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.leaderboard import TournamentLeaderboardService
from app.evaluation.portfolio_models import TournamentPortfolioAccountRecord
from app.models import CanonicalEvent

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_global_leaderboard_aggregates_independent_event_bankrolls() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        event1 = CanonicalEvent(
            id=uuid4(),
            name="Tournament One",
            started_at=NOW,
            ended_at=NOW + timedelta(days=2),
        )
        event2 = CanonicalEvent(
            id=uuid4(),
            name="Tournament Two",
            started_at=NOW + timedelta(days=7),
            ended_at=NOW + timedelta(days=9),
        )
        session.add_all([event1, event2])
        await session.flush()
        session.add_all(
            [
                _account(
                    event1.id,
                    provider="gpt",
                    model="gpt-fixture",
                    pnl=Decimal("2000.00"),
                    max_drawdown_pct=0.10,
                ),
                _account(
                    event2.id,
                    provider="gpt",
                    model="gpt-fixture",
                    pnl=Decimal("-500.00"),
                    max_drawdown_pct=0.20,
                ),
                _account(
                    event1.id,
                    provider="gemini",
                    model="gemini-fixture",
                    pnl=Decimal("1000.00"),
                    max_drawdown_pct=0.05,
                ),
                _account(
                    event2.id,
                    provider="gemini",
                    model="gemini-fixture",
                    pnl=Decimal("1000.00"),
                    max_drawdown_pct=0.08,
                ),
            ]
        )
        await session.flush()

        report = await TournamentLeaderboardService().build_report(session)
        assert report["scope"] == "ALL_CANONICAL_EVENTS"
        assert [row["experiment"]["provider"] for row in report["experiments"]] == [
            "gemini",
            "gpt",
        ]

        gemini = report["experiments"][0]
        assert gemini["rank"] == 1
        assert gemini["event_count"] == 2
        assert gemini["total_initial_bankroll"] == 20000.0
        assert gemini["realized_pnl"] == 2000.0
        assert gemini["realized_roi"] == pytest.approx(0.10)
        assert gemini["profitable_events"] == 2
        assert gemini["profitable_event_rate"] == 1.0
        assert gemini["worst_event_drawdown_pct"] == pytest.approx(0.08)
        assert [event["event_name"] for event in gemini["events"]] == [
            "Tournament One",
            "Tournament Two",
        ]

        gpt = report["experiments"][1]
        assert gpt["rank"] == 2
        assert gpt["realized_pnl"] == 1500.0
        assert gpt["realized_roi"] == pytest.approx(0.075)
        assert gpt["profitable_events"] == 1
        assert gpt["losing_events"] == 1
        assert gpt["worst_event_drawdown_pct"] == pytest.approx(0.20)

    await engine.dispose()


def _account(
    event_id,
    *,
    provider: str,
    model: str,
    pnl: Decimal,
    max_drawdown_pct: float,
) -> TournamentPortfolioAccountRecord:
    initial = Decimal("10000.00")
    return TournamentPortfolioAccountRecord(
        canonical_event_id=event_id,
        provider=provider,
        model=model,
        prompt_version="prompt-v1",
        decision_policy_version="policy-v1",
        ai_view_version="view-v1",
        initial_bankroll=initial,
        cash_balance=initial + pnl,
        locked_balance=Decimal("0.00"),
        realized_pnl=pnl,
        peak_equity=max(initial, initial + pnl),
        max_drawdown=initial * Decimal(str(max_drawdown_pct)),
        max_drawdown_pct=max_drawdown_pct,
        status="ACTIVE",
    )
