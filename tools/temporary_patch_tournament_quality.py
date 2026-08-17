from pathlib import Path


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"target not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, count), encoding="utf-8")


replace(
    "app/evaluation/portfolio.py",
    "    DecisionSnapshotRecord,\n)\n",
    "    DecisionSnapshotRecord,\n    MapResultRecord,\n)\nfrom app.time import ensure_utc\n",
)
replace(
    "app/evaluation/portfolio.py",
    '''        rejection_reason = None
        status = "OPEN"
        if odds is None:
            status = "REJECTED"
            rejection_reason = "MISSING_DECISION_ODDS"
        elif stake > _money(account.cash_balance):
            status = "REJECTED"
            rejection_reason = "INSUFFICIENT_CASH"
''',
    '''        result = await session.scalar(
            select(MapResultRecord).where(
                MapResultRecord.canonical_map_id == scope.canonical_map_id
            )
        )
        decision_available_at = ensure_utc(
            record.response_received_at
            or record.decision_persisted_at
            or record.request_started_at
        )
        rejection_reason = None
        status = "OPEN"
        if result is not None and ensure_utc(result.settled_at) <= decision_available_at:
            status = "REJECTED"
            rejection_reason = "MAP_ALREADY_SETTLED"
        elif odds is None:
            status = "REJECTED"
            rejection_reason = "MISSING_DECISION_ODDS"
        elif stake > _money(account.cash_balance):
            status = "REJECTED"
            rejection_reason = "INSUFFICIENT_CASH"
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''        await self._ledger(
            session,
            account=account,
            position=position,
            entry_type="BET_PLACED",
            cash_delta=-stake,
            locked_delta=stake,
            realized_pnl_delta=_ZERO,
            dedupe_key=f"place:{record.id}",
            occurred_at=record.request_started_at,
        )
        return position
''',
    '''        await self._ledger(
            session,
            account=account,
            position=position,
            entry_type="BET_PLACED",
            cash_delta=-stake,
            locked_delta=stake,
            realized_pnl_delta=_ZERO,
            dedupe_key=f"place:{record.id}",
            occurred_at=record.request_started_at,
        )
        if result is not None:
            await self.settle_map(
                session,
                canonical_map_id=scope.canonical_map_id,
                winner_team_id=result.winner_team_id,
                provider_conflict=bool(result.provider_conflict),
                settled_at=result.settled_at,
            )
        return position
''',
)
