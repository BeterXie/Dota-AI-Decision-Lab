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

# Funding reference belongs to the context method argument, while execution creation
# uses the immutable snapshot timestamp.
replace_once(
    "app/evaluation/portfolio.py",
    "            experiment=experiment,\n"
    "            funding_reference_at=snapshot.decision_at,\n"
    "        )\n"
    "        return _context(account)\n"
    "\n"
    "    async def lane_scope_for_snapshot",
    "            experiment=experiment,\n"
    "            funding_reference_at=funding_reference_at,\n"
    "        )\n"
    "        return _context(account)\n"
    "\n"
    "    async def lane_scope_for_snapshot",
)
replace_once(
    "app/evaluation/portfolio.py",
    "        await self._ensure_account(\n"
    "            session,\n"
    "            canonical_event_id=scope.canonical_event_id,\n"
    "            experiment=experiment,\n"
    "        )\n"
    "        account = await session.scalar(",
    "        await self._ensure_account(\n"
    "            session,\n"
    "            canonical_event_id=scope.canonical_event_id,\n"
    "            experiment=experiment,\n"
    "            funding_reference_at=snapshot.decision_at,\n"
    "        )\n"
    "        account = await session.scalar(",
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

# Add a latency regression: a horizon observation that happened before the AI response
# is diagnostic only and must not contribute to actionable-rate samples.
p = Path("tests/test_tournament_quality.py")
text = p.read_text(encoding="utf-8")
needle = """            session.add(\n                DecisionFutureOdds(\n                    decision_snapshot_id=snapshot.id,\n                    capture_type=\"TIME_HORIZON\",\n                    horizon_seconds=30,\n"""
if needle not in text:
    raise SystemExit("quality future odds insertion target missing")
# Insert one pre-response capture only for the first map.
insert = """            if index == 1:\n                session.add(\n                    DecisionFutureOdds(\n                        decision_snapshot_id=snapshot.id,\n                        capture_type=\"TIME_HORIZON\",\n                        horizon_seconds=15,\n                        triggered_at=snapshot.decision_at,\n                        due_at=snapshot.decision_at + timedelta(seconds=15),\n                        observed_at=decision.response_received_at - timedelta(seconds=1),\n                        odds_a=Decimal(\"1.85\"),\n                        odds_b=Decimal(\"2.15\"),\n                        market_type=\"match_winner\",\n                        match_stage=f\"Map {index}\",\n                        market_status=\"READY\",\n                        capture_policy_version=\"quality-test-v1\",\n                        pair_quality={\"eligible\": True},\n                        pair_skew_seconds=0.0,\n                        status=\"CAPTURED\",\n                    )\n                )\n"""
text = text.replace(needle, insert + needle, 1)
assertion = """        assert latency[\"position_policy\"] == \"FIRST_SETTLED_POSITION_PER_MAP\"\n        horizon = latency[\"horizons\"][\"30\"]\n"""
replacement = """        assert latency[\"position_policy\"] == \"FIRST_SETTLED_POSITION_PER_MAP\"\n        assert latency[\"pre_response_capture_count\"] == 1\n        assert \"15\" not in latency[\"horizons\"]\n        horizon = latency[\"horizons\"][\"30\"]\n"""
if assertion not in text:
    raise SystemExit("quality latency assertion target missing")
text = text.replace(assertion, replacement, 1)
p.write_text(text, encoding="utf-8")

print("PR18 follow-up fixes applied")
