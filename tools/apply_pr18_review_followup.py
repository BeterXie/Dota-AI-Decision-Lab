from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"target missing in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# The batch history grouping must preserve the outer-joined execution columns.
replace_once(
    "app/ai/coordinator.py",
    "        by_provider_model: dict[tuple[str, str], list[tuple]] = {}\n"
    "        for record, decision_at, mode in rows:\n"
    "            by_provider_model.setdefault((record.provider, record.model), []).append(\n"
    "                (record, decision_at, mode)\n"
    "            )\n",
    "        by_provider_model: dict[tuple[str, str], list[tuple]] = {}\n"
    "        for row in rows:\n"
    "            record = row[0]\n"
    "            by_provider_model.setdefault((record.provider, record.model), []).append(tuple(row))\n",
)

# Keep the coordinator regression self-contained regardless of existing module imports.
replace_once(
    "tests/test_ai_coordinator.py",
    "def test_portfolio_prior_rejected_buy_does_not_fake_committed_cash() -> None:\n"
    "    from app.ai.coordinator import _PriorDecision\n"
    "    from app.evaluation.portfolio import PortfolioContext\n",
    "def test_portfolio_prior_rejected_buy_does_not_fake_committed_cash() -> None:\n"
    "    from decimal import Decimal\n"
    "\n"
    "    from app.ai.coordinator import _PriorDecision\n"
    "    from app.evaluation.portfolio import (\n"
    "        PortfolioContext,\n"
    "        TournamentPortfolioService,\n"
    "    )\n",
)

# Funding chronology must be tested by creating the immutable snapshot at the intended
# prematch time, never by mutating a persisted DecisionSnapshotRecord.
replace_once(
    "tests/test_tournament_portfolio.py",
    '''@pytest.mark.asyncio
async def test_event_funding_precedes_prematch_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        event, _, _, _, _, _, snapshot1, _ = await _fixture(session)
        snapshot1.decision_at = NOW - timedelta(minutes=30)
        event.started_at = NOW + timedelta(hours=1)
        context = await service.context_for_snapshot(
            session,
            snapshot_id=snapshot1.id,
            experiment=EXPERIMENT,
        )
        assert context is not None
        funded_at = await session.scalar(
            select(TournamentPortfolioLedgerRecord.occurred_at).where(
                TournamentPortfolioLedgerRecord.portfolio_account_id == context.account_id,
                TournamentPortfolioLedgerRecord.entry_type == "EVENT_FUNDED",
            )
        )
        assert funded_at is not None
        assert funded_at.replace(tzinfo=UTC) == snapshot1.decision_at

    await engine.dispose()
''',
    '''@pytest.mark.asyncio
async def test_event_funding_precedes_prematch_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        decision_at = NOW - timedelta(minutes=30)
        event = CanonicalEvent(name="Prematch Funding Cup", started_at=NOW + timedelta(hours=1))
        team_a = CanonicalTeam(name="Prematch A")
        team_b = CanonicalTeam(name="Prematch B")
        session.add_all([event, team_a, team_b])
        await session.flush()
        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=1,
            scheduled_at=event.started_at,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            scheduled_at=event.started_at,
        )
        session.add(canonical_map)
        await session.flush()
        snapshot = _snapshot(canonical_map.id, team_a.id, team_b.id, 99)
        snapshot.decision_at = decision_at
        snapshot.created_at = decision_at
        session.add(snapshot)
        await session.flush()

        context = await service.context_for_snapshot(
            session,
            snapshot_id=snapshot.id,
            experiment=EXPERIMENT,
        )
        assert context is not None
        funded_at = await session.scalar(
            select(TournamentPortfolioLedgerRecord.occurred_at).where(
                TournamentPortfolioLedgerRecord.portfolio_account_id == context.account_id,
                TournamentPortfolioLedgerRecord.entry_type == "EVENT_FUNDED",
            )
        )
        assert funded_at is not None
        assert funded_at.replace(tzinfo=UTC) == decision_at

    await engine.dispose()
''',
)

# Add a latency regression: a horizon observation that happened before the AI response
# is diagnostic only and must not contribute to actionable-rate samples.
p = Path("tests/test_tournament_quality.py")
text = p.read_text(encoding="utf-8")
needle = """            session.add(\n                DecisionFutureOdds(\n                    decision_snapshot_id=snapshot.id,\n                    capture_type=\"TIME_HORIZON\",\n                    horizon_seconds=30,\n"""
if needle not in text:
    raise SystemExit("quality future odds insertion target missing")
insert = """            if index == 1:\n                session.add(\n                    DecisionFutureOdds(\n                        decision_snapshot_id=snapshot.id,\n                        capture_type=\"TIME_HORIZON\",\n                        horizon_seconds=15,\n                        triggered_at=snapshot.decision_at,\n                        due_at=snapshot.decision_at + timedelta(seconds=15),\n                        observed_at=decision.response_received_at - timedelta(seconds=1),\n                        odds_a=Decimal(\"1.85\"),\n                        odds_b=Decimal(\"2.15\"),\n                        market_type=\"match_winner\",\n                        match_stage=f\"Map {index}\",\n                        market_status=\"READY\",\n                        capture_policy_version=\"quality-test-v1\",\n                        pair_quality={\"eligible\": True},\n                        pair_skew_seconds=0.0,\n                        status=\"CAPTURED\",\n                    )\n                )\n"""
text = text.replace(needle, insert + needle, 1)
assertion = """        assert latency[\"position_policy\"] == \"FIRST_SETTLED_POSITION_PER_MAP\"\n        horizon = latency[\"horizons\"][\"30\"]\n"""
replacement = """        assert latency[\"position_policy\"] == \"FIRST_SETTLED_POSITION_PER_MAP\"\n        assert latency[\"pre_response_capture_count\"] == 1\n        assert \"15\" not in latency[\"horizons\"]\n        horizon = latency[\"horizons\"][\"30\"]\n"""
if assertion not in text:
    raise SystemExit("quality latency assertion target missing")
text = text.replace(assertion, replacement, 1)
p.write_text(text, encoding="utf-8")

print("PR18 follow-up fixes applied")
