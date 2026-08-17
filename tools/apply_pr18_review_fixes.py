from __future__ import annotations

from pathlib import Path
import re


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"target not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, repl: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise SystemExit(f"regex target count={count} in {path}: {pattern[:120]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Portfolio: execution quality, frozen scope, funding chronology.
# ---------------------------------------------------------------------------
path = "app/evaluation/portfolio.py"
text = read(path)

text = text.replace(
    "    async def context_for_snapshot(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        *,\n"
    "        snapshot_id: UUID,\n"
    "        experiment: tuple[str, str, str, str, str],\n"
    "    ) -> PortfolioContext | None:\n"
    "        scope = await self.scope_for_snapshot(session, snapshot_id)\n"
    "        if scope is None:\n"
    "            return None\n"
    "        account = await self._ensure_account(\n"
    "            session,\n"
    "            canonical_event_id=scope.canonical_event_id,\n"
    "            experiment=experiment,\n"
    "        )\n"
    "        return _context(account)\n",
    "    async def context_for_snapshot(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        *,\n"
    "        snapshot_id: UUID,\n"
    "        experiment: tuple[str, str, str, str, str],\n"
    "    ) -> PortfolioContext | None:\n"
    "        scope = await self.scope_for_snapshot(session, snapshot_id)\n"
    "        if scope is None:\n"
    "            return None\n"
    "        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)\n"
    "        return await self.context_for_scope(\n"
    "            session,\n"
    "            scope=scope,\n"
    "            experiment=experiment,\n"
    "            funding_reference_at=snapshot.decision_at if snapshot is not None else None,\n"
    "        )\n"
    "\n"
    "    async def context_for_scope(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        *,\n"
    "        scope: PortfolioScope,\n"
    "        experiment: tuple[str, str, str, str, str],\n"
    "        funding_reference_at: datetime | None = None,\n"
    "    ) -> PortfolioContext:\n"
    "        account = await self._ensure_account(\n"
    "            session,\n"
    "            canonical_event_id=scope.canonical_event_id,\n"
    "            experiment=experiment,\n"
    "            funding_reference_at=funding_reference_at,\n"
    "        )\n"
    "        return _context(account)\n",
    1,
)

text = text.replace(
    "    async def record_decision_position(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        record: AiDecisionRecord,\n"
    "    ) -> TournamentPortfolioPositionRecord | None:\n",
    "    async def record_decision_position(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        record: AiDecisionRecord,\n"
    "        *,\n"
    "        scope: PortfolioScope | None = None,\n"
    "    ) -> TournamentPortfolioPositionRecord | None:\n",
    1,
)

text = text.replace(
    "        scope = await self.scope_for_snapshot(session, record.snapshot_id)\n"
    "        if scope is None:\n"
    "            return None\n"
    "        experiment = (\n",
    "        if scope is None:\n"
    "            scope = await self.scope_for_snapshot(session, record.snapshot_id)\n"
    "        if scope is None:\n"
    "            return None\n"
    "        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)\n"
    "        if snapshot is None:\n"
    "            raise ValueError(\"AI decision references a missing snapshot\")\n"
    "        experiment = (\n",
    1,
)

text = text.replace(
    "        await self._ensure_account(\n"
    "            session,\n"
    "            canonical_event_id=scope.canonical_event_id,\n"
    "            experiment=experiment,\n"
    "        )\n",
    "        await self._ensure_account(\n"
    "            session,\n"
    "            canonical_event_id=scope.canonical_event_id,\n"
    "            experiment=experiment,\n"
    "            funding_reference_at=snapshot.decision_at,\n"
    "        )\n",
    1,
)

text = text.replace(
    "        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)\n"
    "        if snapshot is None:\n"
    "            raise ValueError(\"AI decision references a missing snapshot\")\n"
    "        stake = _money(Decimal(record.stake))\n",
    "        stake = _money(Decimal(record.stake))\n",
    1,
)

text = text.replace(
    "        rejection_reason = None\n"
    "        status = \"OPEN\"\n"
    "        if result is not None and ensure_utc(result.basic_first_usable_at) <= decision_available_at:\n"
    "            status = \"REJECTED\"\n"
    "            rejection_reason = \"MAP_ALREADY_SETTLED\"\n"
    "        elif odds is None:\n",
    "        rejection_reason = None\n"
    "        status = \"OPEN\"\n"
    "        execution_quality_rejection = _execution_quality_rejection(snapshot.canonical_payload)\n"
    "        if result is not None and ensure_utc(result.basic_first_usable_at) <= decision_available_at:\n"
    "            status = \"REJECTED\"\n"
    "            rejection_reason = \"MAP_ALREADY_SETTLED\"\n"
    "        elif execution_quality_rejection is not None:\n"
    "            status = \"REJECTED\"\n"
    "            rejection_reason = execution_quality_rejection\n"
    "        elif odds is None:\n",
    1,
)

text = text.replace(
    "    async def _ensure_account(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        *,\n"
    "        canonical_event_id: UUID,\n"
    "        experiment: tuple[str, str, str, str, str],\n"
    "    ) -> TournamentPortfolioAccountRecord:\n",
    "    async def _ensure_account(\n"
    "        self,\n"
    "        session: AsyncSession,\n"
    "        *,\n"
    "        canonical_event_id: UUID,\n"
    "        experiment: tuple[str, str, str, str, str],\n"
    "        funding_reference_at: datetime | None = None,\n"
    "    ) -> TournamentPortfolioAccountRecord:\n",
    1,
)

text = text.replace(
    "        event = await session.get(CanonicalEvent, canonical_event_id)\n"
    "        funded_at = (\n"
    "            event.started_at\n"
    "            if event is not None and event.started_at is not None\n"
    "            else datetime.now(UTC)\n"
    "        )\n",
    "        event = await session.get(CanonicalEvent, canonical_event_id)\n"
    "        event_started_at = (\n"
    "            ensure_utc(event.started_at)\n"
    "            if event is not None and event.started_at is not None\n"
    "            else None\n"
    "        )\n"
    "        reference_at = (\n"
    "            ensure_utc(funding_reference_at) if funding_reference_at is not None else None\n"
    "        )\n"
    "        if event_started_at is not None and reference_at is not None:\n"
    "            funded_at = min(event_started_at, reference_at)\n"
    "        else:\n"
    "            funded_at = event_started_at or reference_at or datetime.now(UTC)\n",
    1,
)

if "def _execution_quality_rejection(" not in text:
    text = text.replace(
        "\ndef _selected_odds(\n",
        "\ndef _execution_quality_rejection(payload: dict[str, Any]) -> str | None:\n"
        "    snapshot_quality = payload.get(\"quality\")\n"
        "    if not isinstance(snapshot_quality, dict) or snapshot_quality.get(\"eligible\") is not True:\n"
        "        return \"SNAPSHOT_NOT_EXECUTABLE\"\n"
        "    market = payload.get(\"market\")\n"
        "    if not isinstance(market, dict):\n"
        "        return \"MARKET_NOT_EXECUTABLE\"\n"
        "    market_quality = market.get(\"quality\")\n"
        "    if not isinstance(market_quality, dict) or market_quality.get(\"eligible\") is not True:\n"
        "        return \"MARKET_NOT_EXECUTABLE\"\n"
        "    return None\n"
        "\n"
        "\ndef _selected_odds(\n",
        1,
    )
write(path, text)


# ---------------------------------------------------------------------------
# Coordinator: freeze scope in PREPARE and tell the next prompt what executed.
# ---------------------------------------------------------------------------
path = "app/ai/coordinator.py"
text = read(path)
text = text.replace(
    "from app.evaluation.portfolio import PortfolioContext, TournamentPortfolioService\n",
    "from app.evaluation.portfolio import PortfolioContext, PortfolioScope, TournamentPortfolioService\n"
    "from app.evaluation.portfolio_models import TournamentPortfolioPositionRecord\n",
    1,
)
text = text.replace(
    "class _PriorDecision:\n"
    "    decision_at: datetime\n"
    "    mode: str\n"
    "    decision: AiDecision\n"
    "    bankroll_before: float | None = None\n",
    "class _PriorDecision:\n"
    "    decision_at: datetime\n"
    "    mode: str\n"
    "    decision: AiDecision\n"
    "    bankroll_before: float | None = None\n"
    "    execution_status: str | None = None\n"
    "    rejection_reason: str | None = None\n"
    "    execution_cash_before: float | None = None\n",
    1,
)
text = text.replace(
    "    job_enqueued_at: datetime | None = None\n"
    "    job_claimed_at: datetime | None = None\n",
    "    job_enqueued_at: datetime | None = None\n"
    "    job_claimed_at: datetime | None = None\n"
    "    portfolio_scope: PortfolioScope | None = None\n",
    1,
)

old = """        portfolio_context = (\n            await self._portfolio.context_for_snapshot(\n                session,\n                snapshot_id=snapshot.snapshot_id,\n                experiment=experiment,\n            )\n            if self._portfolio is not None\n            else None\n        )\n"""
new = """        portfolio_scope = (\n            await self._portfolio.scope_for_snapshot(session, snapshot.snapshot_id)\n            if self._portfolio is not None\n            else None\n        )\n        portfolio_context = (\n            await self._portfolio.context_for_scope(\n                session,\n                scope=portfolio_scope,\n                experiment=experiment,\n                funding_reference_at=snapshot.decision_at,\n            )\n            if self._portfolio is not None and portfolio_scope is not None\n            else None\n        )\n"""
if text.count(old) < 1:
    raise SystemExit("coordinator prepare portfolio context target missing")
text = text.replace(old, new, 1)
text = text.replace(
    "            job_claimed_at=job_claimed_at,\n"
    "        )\n\n    async def prepare_all",
    "            job_claimed_at=job_claimed_at,\n"
    "            portfolio_scope=portfolio_scope,\n"
    "        )\n\n    async def prepare_all",
    1,
)

# Batch path: scope is shared by all experiments for this immutable snapshot.
marker = """        prior_by_provider_model = await self._load_prior_rows(\n            session,\n            canonical_map_id=canonical_map_id,\n            snapshot=snapshot,\n            providers=self._providers,\n        )\n        prepared: list[PreparedAiDecision] = []\n"""
replacement = """        prior_by_provider_model = await self._load_prior_rows(\n            session,\n            canonical_map_id=canonical_map_id,\n            snapshot=snapshot,\n            providers=self._providers,\n        )\n        portfolio_scope = (\n            await self._portfolio.scope_for_snapshot(session, snapshot.snapshot_id)\n            if self._portfolio is not None\n            else None\n        )\n        prepared: list[PreparedAiDecision] = []\n"""
if marker not in text:
    raise SystemExit("prepare_all scope insertion target missing")
text = text.replace(marker, replacement, 1)

old2 = """            portfolio_context = (\n                await self._portfolio.context_for_snapshot(\n                    session,\n                    snapshot_id=snapshot.snapshot_id,\n                    experiment=experiment,\n                )\n                if self._portfolio is not None\n                else None\n            )\n"""
new2 = """            portfolio_context = (\n                await self._portfolio.context_for_scope(\n                    session,\n                    scope=portfolio_scope,\n                    experiment=experiment,\n                    funding_reference_at=snapshot.decision_at,\n                )\n                if self._portfolio is not None and portfolio_scope is not None\n                else None\n            )\n"""
if old2 not in text:
    raise SystemExit("prepare_all portfolio context target missing")
text = text.replace(old2, new2, 1)
text = text.replace(
    "                    job_claimed_at=job_claimed_at,\n"
    "                )\n"
    "            )\n"
    "        return prepared\n",
    "                    job_claimed_at=job_claimed_at,\n"
    "                    portfolio_scope=portfolio_scope,\n"
    "                )\n"
    "            )\n"
    "        return prepared\n",
    1,
)

text = text.replace(
    "                    await self._portfolio.record_decision_position(session, record)\n",
    "                    await self._portfolio.record_decision_position(\n"
    "                        session, record, scope=prepared.portfolio_scope\n"
    "                    )\n",
    1,
)

# Add execution columns to both prior-row queries.
needle = """                    DecisionSnapshotRecord.mode,\n                )\n                .join(\n                    DecisionSnapshotRecord,\n                    DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,\n                )\n"""
replacement = """                    DecisionSnapshotRecord.mode,\n                    TournamentPortfolioPositionRecord.status,\n                    TournamentPortfolioPositionRecord.rejection_reason,\n                    TournamentPortfolioPositionRecord.cash_before,\n                )\n                .join(\n                    DecisionSnapshotRecord,\n                    DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,\n                )\n                .outerjoin(\n                    TournamentPortfolioPositionRecord,\n                    TournamentPortfolioPositionRecord.ai_decision_id == AiDecisionRecord.id,\n                )\n"""
if text.count(needle) != 2:
    raise SystemExit(f"expected 2 prior query targets, found {text.count(needle)}")
text = text.replace(needle, replacement, 2)

text = text.replace(
    "                    prior_decisions.append(\n"
    "                        self._prior_payload(\n"
    "                            item,\n"
    "                            bankroll_before=frozen_before,\n"
    "                            stake=stake,\n"
    "                        )\n"
    "                    )\n",
    "                    prior_decisions.append(\n"
    "                        self._prior_payload(\n"
    "                            item,\n"
    "                            bankroll_before=frozen_before,\n"
    "                            stake=stake,\n"
    "                            execution_aware=True,\n"
    "                        )\n"
    "                    )\n",
    1,
)
text = text.replace(
    "                self._prior_payload(item, bankroll_before=frozen_before, stake=stake)\n",
    "                self._prior_payload(\n"
    "                    item,\n"
    "                    bankroll_before=frozen_before,\n"
    "                    stake=stake,\n"
    "                    execution_aware=True,\n"
    "                )\n",
    1,
)

old_prior_payload = """    @staticmethod\n    def _prior_payload(item: _PriorDecision, *, bankroll_before: float, stake: float) -> dict:\n        bankroll_after = round(bankroll_before - stake, 2)\n        return {\n            \"decision_at\": item.decision_at.isoformat(),\n            \"mode\": item.mode,\n            \"action\": item.decision.action,\n            \"fair_probability_a\": item.decision.fair_probability_a,\n            \"confidence\": item.decision.confidence,\n            \"market_assessment\": item.decision.market_assessment,\n            \"minimum_acceptable_odds_a\": item.decision.minimum_acceptable_odds_a,\n            \"stake\": stake,\n            \"bankroll_before\": bankroll_before,\n            \"bankroll_after\": bankroll_after,\n            \"bankroll_after_commit\": bankroll_after,\n            \"primary_reasons\": item.decision.primary_reasons,\n            \"blockers\": item.decision.blockers,\n        }\n"""
new_prior_payload = """    @staticmethod\n    def _prior_payload(\n        item: _PriorDecision,\n        *,\n        bankroll_before: float,\n        stake: float,\n        execution_aware: bool = False,\n    ) -> dict:\n        execution_cash_before = (\n            item.execution_cash_before\n            if execution_aware and item.execution_cash_before is not None\n            else bankroll_before\n        )\n        committed = (\n            item.execution_status in {\"OPEN\", \"WON\", \"LOST\", \"VOID\"}\n            if execution_aware\n            else True\n        )\n        bankroll_after = round(\n            execution_cash_before - stake if committed else execution_cash_before,\n            2,\n        )\n        payload = {\n            \"decision_at\": item.decision_at.isoformat(),\n            \"mode\": item.mode,\n            \"action\": item.decision.action,\n            \"fair_probability_a\": item.decision.fair_probability_a,\n            \"confidence\": item.decision.confidence,\n            \"market_assessment\": item.decision.market_assessment,\n            \"minimum_acceptable_odds_a\": item.decision.minimum_acceptable_odds_a,\n            \"stake\": stake,\n            \"bankroll_before\": bankroll_before,\n            \"bankroll_after\": bankroll_after,\n            \"bankroll_after_commit\": bankroll_after,\n            \"primary_reasons\": item.decision.primary_reasons,\n            \"blockers\": item.decision.blockers,\n        }\n        if execution_aware:\n            payload.update(\n                {\n                    \"execution_status\": (\n                        item.execution_status\n                        or (\n                            \"NOT_EXECUTED\"\n                            if item.decision.action in {\"BUY_A\", \"BUY_B\"}\n                            else \"NO_POSITION\"\n                        )\n                    ),\n                    \"rejection_reason\": item.rejection_reason,\n                    \"cash_before_execution\": item.execution_cash_before,\n                }\n            )\n        return payload\n"""
if old_prior_payload not in text:
    raise SystemExit("prior payload target missing")
text = text.replace(old_prior_payload, new_prior_payload, 1)

# Make _prior_from_rows tolerate historical three-tuples while consuming new execution columns.
old_loop = """    for record, decision_at, mode in rows:\n        attempt = (\n"""
new_loop = """    for row in rows:\n        record, decision_at, mode, *execution = row\n        execution_status = execution[0] if len(execution) > 0 else None\n        rejection_reason = execution[1] if len(execution) > 1 else None\n        execution_cash_before = execution[2] if len(execution) > 2 else None\n        attempt = (\n"""
if old_loop not in text:
    raise SystemExit("prior loop target missing")
text = text.replace(old_loop, new_loop, 1)
text = text.replace(
    "            best_by_snapshot[record.snapshot_id] = (attempt, record, decision_at, mode)\n",
    "            best_by_snapshot[record.snapshot_id] = (\n"
    "                attempt,\n"
    "                record,\n"
    "                decision_at,\n"
    "                mode,\n"
    "                execution_status,\n"
    "                rejection_reason,\n"
    "                execution_cash_before,\n"
    "            )\n",
    1,
)
text = text.replace(
    "    for _, record, decision_at, mode in sorted(best_by_snapshot.values(), key=lambda item: item[2]):\n",
    "    for (\n"
    "        _,\n"
    "        record,\n"
    "        decision_at,\n"
    "        mode,\n"
    "        execution_status,\n"
    "        rejection_reason,\n"
    "        execution_cash_before,\n"
    "    ) in sorted(best_by_snapshot.values(), key=lambda item: item[2]):\n",
    1,
)
text = text.replace(
    "                bankroll_before=(\n"
    "                    float(record.bankroll_before) if record.bankroll_before is not None else None\n"
    "                ),\n",
    "                bankroll_before=(\n"
    "                    float(record.bankroll_before) if record.bankroll_before is not None else None\n"
    "                ),\n"
    "                execution_status=execution_status,\n"
    "                rejection_reason=rejection_reason,\n"
    "                execution_cash_before=(\n"
    "                    float(execution_cash_before) if execution_cash_before is not None else None\n"
    "                ),\n",
    1,
)
write(path, text)


# Persist with the exact PREPARE scope.
path = "app/jobs/handlers.py"
text = read(path)
old = """                        await portfolio.record_decision_position(session, record)\n"""
new = """                        await portfolio.record_decision_position(\n                            session,\n                            record,\n                            scope=prepared.portfolio_scope,\n                        )\n"""
if old not in text:
    raise SystemExit("handler portfolio persist target missing")
write(path, text.replace(old, new, 1))


# Lane docs now describe event-scoped accounting.
replace_once(
    "app/ai/lanes.py",
    '    """Process-local ordering for one match/provider/model decision stream.\n',
    '    """Process-local ordering for one account-scope/provider/model decision stream.\n',
)


# ---------------------------------------------------------------------------
# Quality: sample sufficiency, strict identities, deterministic equity batches.
# ---------------------------------------------------------------------------
path = "app/evaluation/quality.py"
text = read(path)
text = text.replace("from dataclasses import dataclass\n", "from dataclasses import dataclass\nfrom decimal import Decimal\n", 1)
text = text.replace(
    "    min_prediction_samples: int = 20\n"
    "    min_roi: float = 0.0\n",
    "    min_prediction_samples: int = 20\n"
    "    min_clv_samples: int = 10\n"
    "    min_market_comparison_samples: int = 20\n"
    "    min_roi: float = 0.0\n",
    1,
)
text = text.replace(
    '                "min_prediction_samples": self._policy.min_prediction_samples,\n'
    '                "min_roi": self._policy.min_roi,\n',
    '                "min_prediction_samples": self._policy.min_prediction_samples,\n'
    '                "min_clv_samples": self._policy.min_clv_samples,\n'
    '                "min_market_comparison_samples": self._policy.min_market_comparison_samples,\n'
    '                "min_roi": self._policy.min_roi,\n',
    1,
)
text = text.replace(
    "                or result.winner_team_id is None\n"
    "                or snapshot.canonical_map_id is None\n"
    "            ):\n"
    "                continue\n"
    "            map_id = snapshot.canonical_map_id\n",
    "                or result.winner_team_id is None\n"
    "                or result.winner_team_id not in {series.team_a_id, series.team_b_id}\n"
    "                or snapshot.canonical_map_id is None\n"
    "            ):\n"
    "                continue\n"
    "            map_id = snapshot.canonical_map_id\n",
    1,
)
text = text.replace(
    "        if quality[\"prediction_sample_count\"] < self._policy.min_prediction_samples:\n"
    "            sample_failures.append(\"MIN_PREDICTION_SAMPLES\")\n",
    "        if quality[\"prediction_sample_count\"] < self._policy.min_prediction_samples:\n"
    "            sample_failures.append(\"MIN_PREDICTION_SAMPLES\")\n"
    "        if quality[\"clv_sample_count\"] < self._policy.min_clv_samples:\n"
    "            sample_failures.append(\"MIN_CLV_SAMPLES\")\n"
    "        if (\n"
    "            quality[\"market_comparison\"][\"sample_count\"]\n"
    "            < self._policy.min_market_comparison_samples\n"
    "        ):\n"
    "            sample_failures.append(\"MIN_MARKET_COMPARISON_SAMPLES\")\n",
    1,
)

old_curve = """        entries = list(\n            (\n                await session.scalars(\n                    select(TournamentPortfolioLedgerRecord)\n                    .where(TournamentPortfolioLedgerRecord.portfolio_account_id == account_id)\n                    .order_by(\n                        TournamentPortfolioLedgerRecord.occurred_at,\n                        TournamentPortfolioLedgerRecord.id,\n                    )\n                )\n            ).all()\n        )\n        return [\n            {\n                \"occurred_at\": entry.occurred_at,\n                \"entry_type\": entry.entry_type,\n                \"equity\": float(entry.equity_after),\n                \"cash\": float(entry.cash_after),\n                \"locked\": float(entry.locked_after),\n                \"realized_pnl_delta\": float(entry.realized_pnl_delta),\n            }\n            for entry in entries\n            if entry.entry_type != \"BET_PLACED\"\n        ]\n"""
new_curve = """        entries = list(\n            (\n                await session.scalars(\n                    select(TournamentPortfolioLedgerRecord)\n                    .where(TournamentPortfolioLedgerRecord.portfolio_account_id == account_id)\n                    .order_by(TournamentPortfolioLedgerRecord.occurred_at)\n                )\n            ).all()\n        )\n        grouped: dict[Any, list[TournamentPortfolioLedgerRecord]] = {}\n        for entry in entries:\n            grouped.setdefault(entry.occurred_at, []).append(entry)\n\n        cash = Decimal(\"0\")\n        locked = Decimal(\"0\")\n        curve: list[dict[str, Any]] = []\n        for occurred_at, batch in sorted(grouped.items(), key=lambda item: item[0]):\n            cash += sum((Decimal(item.cash_delta) for item in batch), Decimal(\"0\"))\n            locked += sum((Decimal(item.locked_delta) for item in batch), Decimal(\"0\"))\n            realized_delta = sum(\n                (Decimal(item.realized_pnl_delta) for item in batch),\n                Decimal(\"0\"),\n            )\n            visible_types = [item.entry_type for item in batch if item.entry_type != \"BET_PLACED\"]\n            if not visible_types:\n                continue\n            entry_type = (\n                visible_types[0]\n                if len(set(visible_types)) == 1\n                else \"SETTLEMENT_BATCH\"\n            )\n            curve.append(\n                {\n                    \"occurred_at\": occurred_at,\n                    \"entry_type\": entry_type,\n                    \"equity\": float(cash + locked),\n                    \"cash\": float(cash),\n                    \"locked\": float(locked),\n                    \"realized_pnl_delta\": float(realized_delta),\n                }\n            )\n        return curve\n"""
if old_curve not in text:
    raise SystemExit("equity curve target missing")
text = text.replace(old_curve, new_curve, 1)

old_market = """    odds_a = None\n    odds_b = None\n    fallback: list[float] = []\n    for item in observations:\n        if not isinstance(item, dict):\n            continue\n        try:\n            price = float(item.get(\"price\"))\n        except TypeError, ValueError:\n            continue\n        if price <= 1:\n            continue\n        fallback.append(price)\n        selection = item.get(\"selection_team_id\")\n        if selection is not None and str(selection) == str(team_a_id):\n            odds_a = price\n        elif selection is not None and str(selection) == str(team_b_id):\n            odds_b = price\n    if odds_a is None or odds_b is None:\n        if len(fallback) < 2:\n            return None\n        odds_a, odds_b = fallback[0], fallback[1]\n"""
new_market = """    odds_a = None\n    odds_b = None\n    for item in observations:\n        if not isinstance(item, dict):\n            continue\n        try:\n            price = float(item.get(\"price\"))\n        except TypeError, ValueError:\n            continue\n        if price <= 1:\n            continue\n        selection = item.get(\"selection_team_id\")\n        if selection is not None and str(selection) == str(team_a_id):\n            odds_a = price\n        elif selection is not None and str(selection) == str(team_b_id):\n            odds_b = price\n    if odds_a is None or odds_b is None:\n        return None\n"""
if old_market not in text:
    raise SystemExit("quality market fallback target missing")
text = text.replace(old_market, new_market, 1)
write(path, text)


# Evaluation must reject foreign winners and map initial prices explicitly by team id.
path = "app/evaluation/metrics.py"
text = read(path)
text = text.replace(
    "        team_a_id = snapshot.canonical_payload.get(\"identity\", {}).get(\"team_a\", {}).get(\"id\")\n"
    "        if not isinstance(team_a_id, str):\n"
    "            return 0\n"
    "        team_a_won = str(result.winner_team_id) == team_a_id\n",
    "        identity = snapshot.canonical_payload.get(\"identity\", {})\n"
    "        team_a_id = identity.get(\"team_a\", {}).get(\"id\") if isinstance(identity, dict) else None\n"
    "        team_b_id = identity.get(\"team_b\", {}).get(\"id\") if isinstance(identity, dict) else None\n"
    "        if not isinstance(team_a_id, str) or not isinstance(team_b_id, str):\n"
    "            return 0\n"
    "        if str(result.winner_team_id) not in {team_a_id, team_b_id}:\n"
    "            return 0\n"
    "        team_a_won = str(result.winner_team_id) == team_a_id\n",
    1,
)
old_initial = """def _initial_prices(\n    snapshot: DecisionSnapshotRecord,\n) -> tuple[float | None, float | None]:\n    observations = snapshot.canonical_payload.get(\"market\", {}).get(\"observations\", [])\n    prices = [\n        float(item[\"price\"])\n        for item in observations\n        if isinstance(item, dict) and item.get(\"price\") is not None\n    ]\n    return (\n        prices[0] if len(prices) > 0 else None,\n        prices[1] if len(prices) > 1 else None,\n    )\n"""
new_initial = """def _initial_prices(\n    snapshot: DecisionSnapshotRecord,\n) -> tuple[float | None, float | None]:\n    identity = snapshot.canonical_payload.get(\"identity\", {})\n    if not isinstance(identity, dict):\n        return None, None\n    team_a_id = (identity.get(\"team_a\") or {}).get(\"id\")\n    team_b_id = (identity.get(\"team_b\") or {}).get(\"id\")\n    if team_a_id is None or team_b_id is None:\n        return None, None\n    observations = snapshot.canonical_payload.get(\"market\", {}).get(\"observations\", [])\n    prices: dict[str, float] = {}\n    for item in observations:\n        if not isinstance(item, dict) or item.get(\"price\") is None:\n            continue\n        selection = item.get(\"selection_team_id\")\n        if selection is None:\n            continue\n        try:\n            price = float(item[\"price\"])\n        except TypeError, ValueError:\n            continue\n        prices[str(selection)] = price\n    return prices.get(str(team_a_id)), prices.get(str(team_b_id))\n"""
if old_initial not in text:
    raise SystemExit("metrics initial prices target missing")
text = text.replace(old_initial, new_initial, 1)
write(path, text)


# ---------------------------------------------------------------------------
# Future odds and latency: validated pairs only, never pre-response observations.
# ---------------------------------------------------------------------------
path = "app/evaluation/future_odds.py"
text = read(path)
old_capture = """        captured.sort(key=lambda item: odds_ids.index(item.odds_id))\n        complete = len(captured) == 2\n        values = {\n            \"triggered_at\": due_at,\n            \"observed_at\": max(item.received_at for item in captured) if complete else observed_at,\n            \"odds_a\": captured[0].price if complete else None,\n            \"odds_b\": captured[1].price if complete else None,\n            \"market_type\": _market_value(snapshot, \"market_type\"),\n            \"match_stage\": _market_value(snapshot, \"match_stage\"),\n            \"market_status\": _market_status(snapshot),\n            \"capture_policy_version\": \"time-horizon-v1\",\n            \"status\": \"CAPTURED\" if complete else \"MISSING\",\n        }\n"""
new_capture = """        captured.sort(key=lambda item: odds_ids.index(item.odds_id))\n        quality_reference_at = (\n            max(item.received_at for item in captured) if captured else observed_at\n        )\n        quality = _closing_pair_quality(\n            snapshot,\n            captured,\n            triggered_at=quality_reference_at,\n            max_age_seconds=self._market_max_age_seconds,\n            max_pair_skew_seconds=self._market_max_pair_skew_seconds,\n        )\n        complete = quality is not None and quality.eligible\n        status = (\n            captured[0].normalized_status\n            if complete and captured[0].normalized_status == captured[1].normalized_status\n            else \"UNKNOWN\"\n        )\n        values = {\n            \"triggered_at\": due_at,\n            \"observed_at\": max(item.received_at for item in captured) if complete else observed_at,\n            \"odds_a\": captured[0].price if complete else None,\n            \"odds_b\": captured[1].price if complete else None,\n            \"market_type\": _market_value(snapshot, \"market_type\"),\n            \"match_stage\": _market_value(snapshot, \"match_stage\"),\n            \"market_status\": status,\n            \"capture_policy_version\": \"time-horizon-v2-pair-validated\",\n            \"pair_quality\": (\n                quality.model_dump(mode=\"json\")\n                if quality is not None\n                else {\n                    \"eligible\": False,\n                    \"blockers\": [\"MARKET_PAIR_IDENTITY_INVALID\"],\n                    \"warnings\": [],\n                }\n            ),\n            \"pair_skew_seconds\": quality.pair_skew_seconds if quality is not None else None,\n            \"status\": \"CAPTURED\" if complete else \"MISSING\",\n        }\n"""
if old_capture not in text:
    raise SystemExit("future odds capture target missing")
write(path, text.replace(old_capture, new_capture, 1))

path = "app/evaluation/latency.py"
text = read(path)
text = text.replace(
    "        horizon_samples: dict[int, list[dict[str, float | bool]]] = defaultdict(list)\n",
    "        horizon_samples: dict[int, list[dict[str, float | bool]]] = defaultdict(list)\n"
    "        pre_response_capture_count = 0\n"
    "        invalid_pair_capture_count = 0\n",
    1,
)
old_latency_loop = """            for capture in by_snapshot.get(record.snapshot_id, ()):\n                horizon = capture.horizon_seconds\n                if horizon is None:\n                    continue\n                future_odds = _selected_future_odds(capture, action=position.action)\n"""
new_latency_loop = """            for capture in by_snapshot.get(record.snapshot_id, ()):\n                horizon = capture.horizon_seconds\n                if horizon is None:\n                    continue\n                pair_quality = capture.pair_quality if isinstance(capture.pair_quality, dict) else {}\n                if pair_quality.get(\"eligible\") is not True:\n                    invalid_pair_capture_count += 1\n                    continue\n                if (\n                    record.response_received_at is not None\n                    and capture.observed_at is not None\n                    and ensure_utc(capture.observed_at) < ensure_utc(record.response_received_at)\n                ):\n                    pre_response_capture_count += 1\n                    continue\n                future_odds = _selected_future_odds(capture, action=position.action)\n"""
if old_latency_loop not in text:
    raise SystemExit("latency loop target missing")
text = text.replace(old_latency_loop, new_latency_loop, 1)
text = text.replace(
    "                    sample[\"observed_after_ai_seconds\"] = max(\n"
    "                        0.0,\n"
    "                        (\n"
    "                            ensure_utc(capture.observed_at)\n"
    "                            - ensure_utc(record.response_received_at)\n"
    "                        ).total_seconds(),\n"
    "                    )\n",
    "                    sample[\"observed_after_ai_seconds\"] = (\n"
    "                        ensure_utc(capture.observed_at)\n"
    "                        - ensure_utc(record.response_received_at)\n"
    "                    ).total_seconds()\n",
    1,
)
text = text.replace(
    '            "interpretation": "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",\n'
    '            "horizons": {\n',
    '            "interpretation": "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",\n'
    '            "pre_response_capture_count": pre_response_capture_count,\n'
    '            "invalid_pair_capture_count": invalid_pair_capture_count,\n'
    '            "horizons": {\n',
    1,
)
text = text.replace(
    '        "interpretation": "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",\n'
    '        "horizons": {},\n',
    '        "interpretation": "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",\n'
    '        "pre_response_capture_count": 0,\n'
    '        "invalid_pair_capture_count": 0,\n'
    '        "horizons": {},\n',
    1,
)
write(path, text)


# ---------------------------------------------------------------------------
# Tests: existing portfolio fixtures must now explicitly be executable.
# ---------------------------------------------------------------------------
for test_path in [
    "tests/test_tournament_portfolio.py",
    "tests/test_tournament_portfolio_late_result.py",
    "tests/test_tournament_portfolio_postgres.py",
    "tests/test_tournament_quality.py",
]:
    text = read(test_path)
    # Add top-level snapshot quality when the fixture has a canonical_payload literal.
    text = re.sub(
        r'(canonical_payload=\{\n(?P<i>\s*)"identity":)',
        lambda m: 'canonical_payload={\n' + m.group('i') + '"quality": {"eligible": True, "blockers": [], "warnings": []},\n' + m.group('i') + '"identity":',
        text,
    )
    # Add market pair quality to every fixture market block that does not already have it.
    text = re.sub(
        r'("market": \{\n)(?P<i>\s*)("observations": \[)',
        lambda m: m.group(1) + m.group('i') + '"quality": {"eligible": True, "blockers": [], "warnings": []},\n' + m.group('i') + m.group(3),
        text,
    )
    write(test_path, text)

# Existing quality fixture needs explicit new minimums.
replace_once(
    "tests/test_tournament_quality.py",
    "            min_prediction_samples=2,\n            min_roi=0.0,\n",
    "            min_prediction_samples=2,\n            min_clv_samples=2,\n            min_market_comparison_samples=2,\n            min_roi=0.0,\n",
)
# Existing manually inserted horizon capture is intentionally valid.
text = read("tests/test_tournament_quality.py")
if 'pair_quality={"eligible": True}' not in text:
    text = text.replace(
        '                    capture_policy_version="quality-test-v1",\n',
        '                    capture_policy_version="quality-test-v1",\n                    pair_quality={"eligible": True},\n',
    )
write("tests/test_tournament_quality.py", text)

# Add focused regression tests without bloating unrelated fixtures.
portfolio_tests = read("tests/test_tournament_portfolio.py")
if "test_non_executable_snapshot_does_not_move_cash" not in portfolio_tests:
    portfolio_tests += '''\n\n@pytest.mark.asyncio\nasync def test_non_executable_snapshot_does_not_move_cash() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    service = TournamentPortfolioService(initial_bankroll=10_000)\n\n    async with factory() as session, session.begin():\n        event, _, _, _, _, _, snapshot1, _ = await _fixture(session)\n        snapshot1.canonical_payload["market"]["quality"] = {\n            "eligible": False,\n            "blockers": ["MARKET_STALE"],\n            "warnings": [],\n        }\n        decision = _decision(snapshot1, action="BUY_A", stake=1000)\n        session.add(decision)\n        await session.flush()\n        position = await service.record_decision_position(session, decision)\n        assert position is not None\n        assert position.status == "REJECTED"\n        assert position.rejection_reason == "MARKET_NOT_EXECUTABLE"\n        account = await session.scalar(\n            select(TournamentPortfolioAccountRecord).where(\n                TournamentPortfolioAccountRecord.canonical_event_id == event.id\n            )\n        )\n        assert account is not None\n        assert account.cash_balance == Decimal("10000.00")\n        assert account.locked_balance == Decimal("0.00")\n\n    await engine.dispose()\n\n\n@pytest.mark.asyncio\nasync def test_event_funding_precedes_prematch_snapshot() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    service = TournamentPortfolioService(initial_bankroll=10_000)\n\n    async with factory() as session, session.begin():\n        event, _, _, _, _, _, snapshot1, _ = await _fixture(session)\n        snapshot1.decision_at = NOW - timedelta(minutes=30)\n        event.started_at = NOW + timedelta(hours=1)\n        context = await service.context_for_snapshot(\n            session,\n            snapshot_id=snapshot1.id,\n            experiment=EXPERIMENT,\n        )\n        assert context is not None\n        funded_at = await session.scalar(\n            select(TournamentPortfolioLedgerRecord.occurred_at).where(\n                TournamentPortfolioLedgerRecord.portfolio_account_id == context.account_id,\n                TournamentPortfolioLedgerRecord.entry_type == "EVENT_FUNDED",\n            )\n        )\n        assert funded_at is not None\n        assert funded_at.replace(tzinfo=UTC) == snapshot1.decision_at\n\n    await engine.dispose()\n'''
write("tests/test_tournament_portfolio.py", portfolio_tests)

quality_tests = read("tests/test_tournament_quality.py")
if "test_gate_requires_clv_and_market_comparison_samples" not in quality_tests:
    quality_tests += '''\n\ndef test_gate_requires_clv_and_market_comparison_samples() -> None:\n    service = TournamentQualityService(\n        policy=QualityGatePolicy(\n            min_settled_maps=2,\n            min_settled_bets=2,\n            min_prediction_samples=2,\n            min_clv_samples=2,\n            min_market_comparison_samples=2,\n        )\n    )\n    portfolio = {\n        "bet_count": 2,\n        "roi": 0.1,\n        "max_drawdown_pct": 0.1,\n        "status": "ACTIVE",\n    }\n    quality = {\n        "settled_maps": 2,\n        "prediction_sample_count": 2,\n        "clv_sample_count": 1,\n        "average_clv": 0.1,\n        "market_comparison": {\n            "sample_count": 1,\n            "brier_improvement_vs_market": 0.1,\n        },\n    }\n    gate = service._gate(portfolio, quality)\n    assert gate["status"] == "INSUFFICIENT_SAMPLE"\n    assert gate["failures"] == ["MIN_CLV_SAMPLES", "MIN_MARKET_COMPARISON_SAMPLES"]\n\n\ndef test_market_baseline_requires_explicit_team_identity() -> None:\n    from app.evaluation.quality import _market_probability_a\n\n    team_a = uuid4()\n    team_b = uuid4()\n    payload = {\n        "market": {\n            "observations": [\n                {"price": "1.80"},\n                {"price": "2.20"},\n            ]\n        }\n    }\n    assert _market_probability_a(payload, team_a_id=team_a, team_b_id=team_b) is None\n'''
write("tests/test_tournament_quality.py", quality_tests)

# Direct unit for rejected prior execution semantics.
ai_tests = read("tests/test_ai_coordinator.py")
if "test_portfolio_prior_rejected_buy_does_not_fake_committed_cash" not in ai_tests:
    ai_tests += '''\n\ndef test_portfolio_prior_rejected_buy_does_not_fake_committed_cash() -> None:\n    from app.ai.coordinator import _PriorDecision\n    from app.evaluation.portfolio import PortfolioContext\n\n    coordinator = AiCoordinator(\n        [],\n        timeout_seconds=1,\n        portfolio=TournamentPortfolioService(initial_bankroll=10_000),\n    )\n    prior = _PriorDecision(\n        decision_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),\n        mode="LIVE_BASIC",\n        decision=AiDecision(\n            action="BUY_A",\n            fair_probability_a=0.6,\n            confidence=0.7,\n            market_assessment="UNDERPRICED",\n            minimum_acceptable_odds_a=1.7,\n            stake=4000,\n            primary_reasons=["fixture"],\n            blockers=[],\n        ),\n        bankroll_before=10_000.0,\n        execution_status="REJECTED",\n        rejection_reason="INSUFFICIENT_CASH",\n        execution_cash_before=3_000.0,\n    )\n    context = PortfolioContext(\n        account_id=uuid4(),\n        canonical_event_id=uuid4(),\n        initial_bankroll=Decimal("10000.00"),\n        cash_balance=Decimal("3000.00"),\n        locked_balance=Decimal("7000.00"),\n        realized_pnl=Decimal("0.00"),\n        peak_equity=Decimal("10000.00"),\n        max_drawdown=Decimal("0.00"),\n        max_drawdown_pct=0.0,\n    )\n    payload = coordinator._bankroll_context([prior], portfolio_context=context)\n    item = payload["prior_decisions"][0]\n    assert item["execution_status"] == "REJECTED"\n    assert item["rejection_reason"] == "INSUFFICIENT_CASH"\n    assert item["cash_before_execution"] == 3000.0\n    assert item["bankroll_after_commit"] == 3000.0\n'''
write("tests/test_ai_coordinator.py", ai_tests)

print("PR18 review fixes applied")
