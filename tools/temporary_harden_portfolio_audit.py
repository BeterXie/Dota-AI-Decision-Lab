from pathlib import Path


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"target not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, count), encoding="utf-8")


replace(
    "app/evaluation/portfolio_models.py",
    '''    action: Mapped[str] = mapped_column(String(16), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    odds: Mapped[Decimal | None] = mapped_column(Numeric(12, 5))
''',
    '''    action: Mapped[str] = mapped_column(String(16), nullable=False)
    cash_before: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    odds: Mapped[Decimal | None] = mapped_column(Numeric(12, 5))
''',
)
replace(
    "migrations/versions/0035_ai_tournament_portfolio.py",
    '''        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("stake", sa.Numeric(14, 2), nullable=False),
''',
    '''        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("cash_before", sa.Numeric(14, 2), nullable=False),
        sa.Column("stake", sa.Numeric(14, 2), nullable=False),
''',
)

# Recheck the unique decision after acquiring the shared account lock, and freeze
# actual execution cash rather than relying on the model's earlier view.
replace(
    "app/evaluation/portfolio.py",
    '''        if account is None:
            raise RuntimeError("tournament portfolio account disappeared")

        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)
''',
    '''        if account is None:
            raise RuntimeError("tournament portfolio account disappeared")
        existing = await session.scalar(
            select(TournamentPortfolioPositionRecord).where(
                TournamentPortfolioPositionRecord.ai_decision_id == record.id
            )
        )
        if existing is not None:
            return existing

        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''        result = await session.scalar(
            select(MapResultRecord).where(
                MapResultRecord.canonical_map_id == scope.canonical_map_id
            )
        )
        decision_available_at = ensure_utc(
''',
    '''        result = await session.scalar(
            select(MapResultRecord).where(
                MapResultRecord.canonical_map_id == scope.canonical_map_id
            )
        )
        cash_before = _money(account.cash_balance)
        decision_available_at = ensure_utc(
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''        if result is not None and ensure_utc(result.settled_at) <= decision_available_at:
            status = "REJECTED"
            rejection_reason = "MAP_ALREADY_SETTLED"
''',
    '''        if (
            result is not None
            and ensure_utc(result.basic_first_usable_at) <= decision_available_at
        ):
            status = "REJECTED"
            rejection_reason = "MAP_ALREADY_SETTLED"
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''        elif stake > _money(account.cash_balance):
            status = "REJECTED"
            rejection_reason = "INSUFFICIENT_CASH"

        position = TournamentPortfolioPositionRecord(
''',
    '''        elif stake > cash_before:
            status = "REJECTED"
            rejection_reason = "INSUFFICIENT_CASH"

        position = TournamentPortfolioPositionRecord(
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''            canonical_map_id=scope.canonical_map_id,
            action=decision.action,
            stake=stake,
''',
    '''            canonical_map_id=scope.canonical_map_id,
            action=decision.action,
            cash_before=cash_before,
            stake=stake,
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''        account.cash_balance = _money(account.cash_balance - stake)
''',
    '''        account.cash_balance = _money(cash_before - stake)
''',
)

# Unknown winner identities are voided rather than charged as losses.
replace(
    "app/evaluation/portfolio.py",
    '''            for position in positions:
                stake = _money(position.stake)
                if provider_conflict or winner_team_id is None:
                    payout = stake
''',
    '''            for position in positions:
                stake = _money(position.stake)
                winner_is_valid = winner_team_id in {series.team_a_id, series.team_b_id}
                if provider_conflict or not winner_is_valid:
                    payout = stake
''',
)

# Portfolio money must never guess team/price mapping by observation order.
quality_path = Path("app/evaluation/portfolio.py")
text = quality_path.read_text(encoding="utf-8")
start = text.index("def _selected_odds(\n")
end = text.index("\n\ndef _money(", start)
strict_odds = '''def _selected_odds(
    payload: dict[str, Any],
    *,
    action: str,
    team_a_id: UUID,
    team_b_id: UUID,
) -> Decimal | None:
    market = payload.get("market")
    if not isinstance(market, dict):
        return None
    observations = market.get("observations")
    if not isinstance(observations, list):
        return None
    target = team_a_id if action == "BUY_A" else team_b_id
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        selection_team_id = observation.get("selection_team_id")
        if selection_team_id is None or str(selection_team_id) != str(target):
            continue
        raw_price = observation.get("price")
        if raw_price is None:
            return None
        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError):
            return None
        return price if price > 1 else None
    return None
'''
quality_path.write_text(text[:start] + strict_odds + text[end:], encoding="utf-8")

# Risk sizing is based on actual execution cash, not the potentially stale AI view.
replace(
    "app/evaluation/quality.py",
    '''        stake_ratios = [
            float(position.stake) / float(decision.bankroll_before)
            for position, decision in position_pairs
            if decision.bankroll_before is not None
            and float(decision.bankroll_before) > 0
            and position.status != "REJECTED"
        ]
''',
    '''        stake_ratios = [
            float(position.stake) / float(position.cash_before)
            for position, _ in position_pairs
            if float(position.cash_before) > 0 and position.status != "REJECTED"
        ]
''',
)

# Add same-decision cross-worker idempotency regression.
postgres_test = Path("tests/test_tournament_portfolio_postgres.py")
text = postgres_test.read_text(encoding="utf-8")
if "test_postgres_same_decision_position_creation_is_idempotent" not in text:
    text += r'''

@pytest.mark.asyncio
async def test_postgres_same_decision_position_creation_is_idempotent() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL row-lock regression requires DATABASE_URL")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)
    now = datetime.now(UTC).replace(microsecond=0)
    experiment = ("idempotent", "fixture", "prompt", "policy", "view")

    async with factory() as session, session.begin():
        event = CanonicalEvent(name=f"Idempotent Cup {uuid4()}", started_at=now)
        team_a = CanonicalTeam(name=f"A-{uuid4()}")
        team_b = CanonicalTeam(name=f"B-{uuid4()}")
        session.add_all([event, team_a, team_b])
        await session.flush()
        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=1,
            scheduled_at=now,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=1, scheduled_at=now)
        session.add(canonical_map)
        await session.flush()
        snapshot = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map.id,
            decision_at=now + timedelta(minutes=1),
            created_at=now + timedelta(minutes=1),
            mode="LIVE_BASIC",
            canonical_payload={
                "identity": {
                    "team_a": {"id": str(team_a.id)},
                    "team_b": {"id": str(team_b.id)},
                },
                "market": {
                    "observations": [
                        {"selection_team_id": str(team_a.id), "price": "1.90"},
                        {"selection_team_id": str(team_b.id), "price": "2.10"},
                    ]
                },
            },
            snapshot_hash=f"idempotent-{uuid4()}",
        )
        session.add(snapshot)
        await session.flush()
        decision = _decision(snapshot, experiment=experiment, stake=1000, offset=0)
        session.add(decision)
        await session.flush()
        await service.context_for_snapshot(
            session,
            snapshot_id=snapshot.id,
            experiment=experiment,
        )
        event_id = event.id
        decision_id = decision.id

    async def place():
        async with factory() as session, session.begin():
            decision = await session.get(AiDecisionRecord, decision_id)
            assert decision is not None
            position = await service.record_decision_position(session, decision)
            assert position is not None
            return position.id

    first, second = await asyncio.gather(place(), place())
    assert first == second

    async with factory() as session:
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event_id,
                TournamentPortfolioAccountRecord.provider == experiment[0],
            )
        )
        assert account is not None
        positions = list(
            (
                await session.scalars(
                    select(TournamentPortfolioPositionRecord).where(
                        TournamentPortfolioPositionRecord.portfolio_account_id == account.id
                    )
                )
            ).all()
        )
        assert len(positions) == 1
        assert positions[0].cash_before == Decimal("10000.00")
        assert account.cash_balance == Decimal("9000.00")
        assert account.locked_balance == Decimal("1000.00")

    await engine.dispose()
'''
postgres_test.write_text(text, encoding="utf-8")

# Validate invalid winner identity cannot burn bankroll.
core_test = Path("tests/test_tournament_portfolio.py")
text = core_test.read_text(encoding="utf-8")
if "test_unknown_winner_identity_voids_positions" not in text:
    text += r'''

@pytest.mark.asyncio
async def test_unknown_winner_identity_voids_positions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        event, _, _, _, map1, _, snapshot1, _ = await _fixture(session)
        outsider = CanonicalTeam(name="Outsider")
        session.add(outsider)
        await session.flush()
        decision = _decision(snapshot1, action="BUY_A", stake=2500)
        session.add(decision)
        await session.flush()
        position = await service.record_decision_position(session, decision)
        assert position is not None and position.status == "OPEN"
        await service.settle_map(
            session,
            canonical_map_id=map1.id,
            winner_team_id=outsider.id,
            provider_conflict=False,
        )
        assert position.status == "VOID"
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event.id
            )
        )
        assert account is not None
        assert account.cash_balance == Decimal("10000.00")
        assert account.realized_pnl == Decimal("0.00")

    await engine.dispose()
'''
core_test.write_text(text, encoding="utf-8")
