from pathlib import Path

quality = Path("app/evaluation/quality.py")
text = quality.read_text(encoding="utf-8")
old = "from app.domain.decision import AiDecision\nfrom app.evaluation.metrics import brier_score, log_loss\n"
new = (
    "from app.domain.decision import AiDecision\n"
    "from app.evaluation.latency import LatencyExecutionService\n"
    "from app.evaluation.metrics import brier_score, log_loss\n"
)
if old not in text:
    raise SystemExit("quality import insertion point not found")
text = text.replace(old, new, 1)
old = """        self._portfolio = portfolio or TournamentPortfolioService()
        self._policy = policy or QualityGatePolicy()
"""
new = """        self._portfolio = portfolio or TournamentPortfolioService()
        self._policy = policy or QualityGatePolicy()
        self._latency = LatencyExecutionService()
"""
if old not in text:
    raise SystemExit("quality init insertion point not found")
text = text.replace(old, new, 1)
old = """        gate = self._gate(portfolio_row, metrics)
        curve = await self._equity_curve(session, account_id=account_id)
        return {
            "experiment": identity,
            "portfolio": portfolio_row,
            "quality": metrics,
            "gate": gate,
            "equity_curve": curve,
        }
"""
new = """        gate = self._gate(portfolio_row, metrics)
        curve = await self._equity_curve(session, account_id=account_id)
        execution_latency = await self._latency.build_experiment_report(
            session,
            account_id=account_id,
        )
        return {
            "experiment": identity,
            "portfolio": portfolio_row,
            "quality": metrics,
            "execution_latency": execution_latency,
            "gate": gate,
            "equity_curve": curve,
        }
"""
if old not in text:
    raise SystemExit("quality return insertion point not found")
quality.write_text(text.replace(old, new, 1), encoding="utf-8")

init = Path("app/evaluation/__init__.py")
text = init.read_text(encoding="utf-8")
text = text.replace(
    "from app.evaluation.future_odds import FutureOddsCaptureType, FutureOddsService\n",
    "from app.evaluation.future_odds import FutureOddsCaptureType, FutureOddsService\n"
    "from app.evaluation.latency import LatencyExecutionService\n",
    1,
)
text = text.replace(
    '    "FutureOddsService",\n',
    '    "FutureOddsService",\n    "LatencyExecutionService",\n',
    1,
)
init.write_text(text, encoding="utf-8")

test = Path("tests/test_tournament_quality.py")
text = test.read_text(encoding="utf-8")
text = text.replace(
    "    DecisionEvaluationRecord,\n    DecisionSnapshotRecord,\n",
    "    DecisionEvaluationRecord,\n    DecisionFutureOdds,\n    DecisionSnapshotRecord,\n",
    1,
)
needle = '''            evaluation.clv = 0.02
            if index == 1:
'''
replacement = '''            evaluation.clv = 0.02
            session.add(
                DecisionFutureOdds(
                    decision_snapshot_id=snapshot.id,
                    capture_type="TIME_HORIZON",
                    horizon_seconds=30,
                    triggered_at=snapshot.decision_at,
                    due_at=snapshot.decision_at + timedelta(seconds=30),
                    observed_at=decision.response_received_at + timedelta(seconds=30),
                    odds_a=Decimal("1.80"),
                    odds_b=Decimal("2.20"),
                    market_type="match_winner",
                    match_stage=f"Map {index}",
                    market_status="READY",
                    capture_policy_version="quality-test-v1",
                    pair_quality={"eligible": True},
                    pair_skew_seconds=0.0,
                    status="CAPTURED",
                )
            )
            if index == 1:
'''
if needle not in text:
    raise SystemExit("quality future odds insertion point not found")
text = text.replace(needle, replacement, 1)
needle = '''        assert experiment["gate"] == {
            "mode": "SHADOW_ONLY",
            "status": "PASS",
            "failures": [],
        }
        assert experiment["equity_curve"][0]["entry_type"] == "EVENT_FUNDED"
'''
replacement = '''        assert experiment["gate"] == {
            "mode": "SHADOW_ONLY",
            "status": "PASS",
            "failures": [],
        }
        latency = experiment["execution_latency"]
        assert latency["position_policy"] == "FIRST_SETTLED_POSITION_PER_MAP"
        horizon = latency["horizons"]["30"]
        assert horizon["sample_count"] == 2
        assert horizon["actionable_rate"] == 1.0
        assert horizon["average_model_edge_vs_break_even"] == pytest.approx(
            0.60 - (1.0 / 1.80)
        )
        assert horizon["average_odds_slippage_pct"] == pytest.approx((1.80 / 1.90) - 1.0)
        assert horizon["average_observed_after_ai_seconds"] == pytest.approx(30.0)
        assert experiment["equity_curve"][0]["entry_type"] == "EVENT_FUNDED"
'''
if needle not in text:
    raise SystemExit("quality latency assertion point not found")
test.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
