from pathlib import Path


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"target not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, count), encoding="utf-8")


replace(
    "app/ai/base.py",
    '''- BUY_A/BUY_B require 0 < stake <= virtual_bankroll.bankroll_before.
  NO_BUY/INSUFFICIENT_DATA use stake null/0. Stake is virtual audit capital only.
''',
    '''- BUY_A/BUY_B require 0 < stake <= virtual_bankroll.bankroll_before.
  If virtual_bankroll.scope is UNRESOLVED_CANONICAL_EVENT, or bankroll_before is 0,
  do not BUY: the tournament account cannot be identified safely yet.
  NO_BUY/INSUFFICIENT_DATA use stake null/0. Stake is virtual audit capital only.
''',
)

replace(
    "app/ai/coordinator.py",
    '''        if portfolio_context is None:
            bankroll_before = self._virtual_bankroll
            prior_decisions: list[dict] = []
            for item in prior:
                stake = round(float(item.decision.stake or 0.0), 2)
                prior_decisions.append(
                    self._prior_payload(item, bankroll_before=bankroll_before, stake=stake)
                )
                bankroll_before = round(bankroll_before - stake, 2)
            return {
                "initial": self._virtual_bankroll,
                "bankroll_before": bankroll_before,
                "unsettled_stakes": round(self._virtual_bankroll - bankroll_before, 2),
                "units": "virtual-units",
                "prior_decisions": prior_decisions[-self._prior_decisions_limit :],
            }
''',
    '''        if portfolio_context is None:
            if self._portfolio is not None:
                prior_decisions: list[dict] = []
                for item in prior:
                    stake = round(float(item.decision.stake or 0.0), 2)
                    frozen_before = item.bankroll_before if item.bankroll_before is not None else 0.0
                    prior_decisions.append(
                        self._prior_payload(
                            item,
                            bankroll_before=frozen_before,
                            stake=stake,
                        )
                    )
                return {
                    "scope": "UNRESOLVED_CANONICAL_EVENT",
                    "canonical_event_id": None,
                    "initial": 0.0,
                    "bankroll_before": 0.0,
                    "cash_balance": 0.0,
                    "locked_balance": 0.0,
                    "equity": 0.0,
                    "realized_pnl": 0.0,
                    "unsettled_stakes": 0.0,
                    "units": "virtual-units",
                    "reason": "EVENT_IDENTITY_UNRESOLVED",
                    "prior_decisions": prior_decisions[-self._prior_decisions_limit :],
                }

            bankroll_before = self._virtual_bankroll
            prior_decisions = []
            for item in prior:
                stake = round(float(item.decision.stake or 0.0), 2)
                prior_decisions.append(
                    self._prior_payload(item, bankroll_before=bankroll_before, stake=stake)
                )
                bankroll_before = round(bankroll_before - stake, 2)
            return {
                "initial": self._virtual_bankroll,
                "bankroll_before": bankroll_before,
                "unsettled_stakes": round(self._virtual_bankroll - bankroll_before, 2),
                "units": "virtual-units",
                "prior_decisions": prior_decisions[-self._prior_decisions_limit :],
            }
''',
)

# A position does not exist before the AI response exists. Keep snapshot odds frozen,
# but place the virtual order and lock cash at the response-available timestamp.
replace(
    "app/evaluation/portfolio.py",
    '''            rejection_reason=rejection_reason,
            opened_at=record.request_started_at,
        )
''',
    '''            rejection_reason=rejection_reason,
            opened_at=decision_available_at,
        )
''',
)
replace(
    "app/evaluation/portfolio.py",
    '''            dedupe_key=f"place:{record.id}",
            occurred_at=record.request_started_at,
        )
''',
    '''            dedupe_key=f"place:{record.id}",
            occurred_at=decision_available_at,
        )
''',
)

# Prediction-quality independence uses the first evaluable probability forecast,
# not merely the first parse-success row (which may be INSUFFICIENT_DATA with no p).
replace(
    "app/evaluation/quality.py",
    '                "prediction": "FIRST_SUCCESSFUL_DECISION_PER_MAP",\n',
    '                "prediction": "FIRST_EVALUABLE_FORECAST_PER_MAP",\n',
)
replace(
    "app/evaluation/quality.py",
    '''            if map_id not in map_forecasts:
                map_forecasts[map_id] = {
                    "ai_brier": (
                        float(evaluation.brier_score)
                        if evaluation is not None and evaluation.brier_score is not None
                        else None
                    ),
                    "ai_log_loss": (
                        float(evaluation.log_loss)
                        if evaluation is not None and evaluation.log_loss is not None
                        else None
                    ),
                    "market_brier": float(market_brier) if market_brier is not None else None,
                    "market_log_loss": (
                        float(market_loss) if market_loss is not None else None
                    ),
                }
''',
    '''            ai_brier = (
                float(evaluation.brier_score)
                if evaluation is not None and evaluation.brier_score is not None
                else None
            )
            ai_log_loss = (
                float(evaluation.log_loss)
                if evaluation is not None and evaluation.log_loss is not None
                else None
            )
            if map_id not in map_forecasts and ai_brier is not None and ai_log_loss is not None:
                map_forecasts[map_id] = {
                    "ai_brier": ai_brier,
                    "ai_log_loss": ai_log_loss,
                    "market_brier": float(market_brier) if market_brier is not None else None,
                    "market_log_loss": (
                        float(market_loss) if market_loss is not None else None
                    ),
                }
''',
)

# Assert placement chronology in the core portfolio test.
portfolio_test = Path("tests/test_tournament_portfolio.py")
text = portfolio_test.read_text(encoding="utf-8")
needle = '''        position1 = await service.record_decision_position(session, first)
        assert position1 is not None and position1.status == "OPEN"

        second = _decision(snapshot2, action="BUY_B", stake=4000)
'''
replacement = '''        position1 = await service.record_decision_position(session, first)
        assert position1 is not None and position1.status == "OPEN"
        assert position1.opened_at == first.response_received_at
        placed_at = await session.scalar(
            select(TournamentPortfolioLedgerRecord.occurred_at).where(
                TournamentPortfolioLedgerRecord.position_id == position1.id,
                TournamentPortfolioLedgerRecord.entry_type == "BET_PLACED",
            )
        )
        assert placed_at == first.response_received_at

        second = _decision(snapshot2, action="BUY_B", stake=4000)
'''
if needle not in text:
    raise SystemExit("portfolio chronology assertion point not found")
portfolio_test.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

# Insert an earlier INSUFFICIENT_DATA row on map 1. It must not consume that map's
# independent forecast sample; the later evaluable BUY remains the gate sample.
quality_test = Path("tests/test_tournament_quality.py")
text = quality_test.read_text(encoding="utf-8")
needle = '''            evaluation.clv = 0.02
            session.add(
                DecisionFutureOdds(
'''
replacement = '''            evaluation.clv = 0.02
            if index == 1:
                insufficient_snapshot = DecisionSnapshotRecord(
                    id=uuid4(),
                    canonical_map_id=canonical_map.id,
                    decision_at=snapshot.decision_at - timedelta(minutes=1),
                    created_at=snapshot.decision_at - timedelta(minutes=1),
                    mode="LIVE_BASIC",
                    canonical_payload=snapshot.canonical_payload,
                    snapshot_hash=f"quality-insufficient-{uuid4()}",
                )
                session.add(insufficient_snapshot)
                await session.flush()
                insufficient = _insufficient_decision(insufficient_snapshot)
                session.add(insufficient)
                await session.flush()
                assert await EvaluationService().evaluate_snapshot(
                    session,
                    snapshot_id=insufficient_snapshot.id,
                ) == 1
            session.add(
                DecisionFutureOdds(
'''
if needle not in text:
    raise SystemExit("quality insufficient insertion point not found")
text = text.replace(needle, replacement, 1)
text = text.replace(
    '''        assert experiment["quality"]["successful_decisions"] == 3
        assert experiment["quality"]["prediction_sample_count"] == 2
        assert experiment["quality"]["decision_level"]["prediction_sample_count"] == 3
        assert experiment["quality"]["sample_policy"]["portfolio"] == "ALL_EXECUTED_POSITIONS"
''',
    '''        assert experiment["quality"]["successful_decisions"] == 4
        assert experiment["quality"]["prediction_sample_count"] == 2
        assert experiment["quality"]["decision_level"]["prediction_sample_count"] == 3
        assert (
            experiment["quality"]["sample_policy"]["prediction"]
            == "FIRST_EVALUABLE_FORECAST_PER_MAP"
        )
        assert experiment["quality"]["sample_policy"]["portfolio"] == "ALL_EXECUTED_POSITIONS"
''',
    1,
)
text += '''\n\ndef _insufficient_decision(snapshot: DecisionSnapshotRecord) -> AiDecisionRecord:\n    provider, model, prompt, policy, view = EXPERIMENT\n    return AiDecisionRecord(\n        snapshot_id=snapshot.id,\n        snapshot_hash=snapshot.snapshot_hash,\n        provider=provider,\n        model=model,\n        model_version=model,\n        prompt_version=prompt,\n        decision_policy_version=policy,\n        ai_view_version=view,\n        ai_input_hash=f"quality-insufficient-{uuid4()}",\n        bankroll_before=Decimal("10000.00"),\n        stake=None,\n        request_started_at=snapshot.decision_at,\n        response_received_at=snapshot.decision_at + timedelta(seconds=1),\n        latency_seconds=1.0,\n        normalized_response={\n            "action": "INSUFFICIENT_DATA",\n            "fair_probability_a": None,\n            "confidence": 0.2,\n            "market_assessment": "UNKNOWN",\n            "minimum_acceptable_odds_a": None,\n            "stake": None,\n            "primary_reasons": ["not enough evidence yet"],\n            "blockers": ["WAIT_FOR_LIVE_DATA"],\n        },\n        raw_response={"fixture": True},\n        parse_status="SUCCESS",\n    )\n'''
quality_test.write_text(text, encoding="utf-8")
