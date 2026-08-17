from pathlib import Path

portfolio = Path("app/evaluation/portfolio.py")
text = portfolio.read_text(encoding="utf-8")
text = text.replace(
    "from decimal import ROUND_HALF_UP, Decimal\n",
    "from decimal import ROUND_HALF_UP, Decimal, InvalidOperation\n",
    1,
)
old = """        try:\n            price = Decimal(str(raw_price))\n        except Exception:\n            continue\n"""
new = """        try:\n            price = Decimal(str(raw_price))\n        except (InvalidOperation, ValueError):\n            continue\n"""
if old not in text:
    raise SystemExit("portfolio Decimal exception target not found")
portfolio.write_text(text.replace(old, new, 1), encoding="utf-8")

quality = Path("app/evaluation/quality.py")
text = quality.read_text(encoding="utf-8")
text = text.replace(
    "from sqlalchemy import select\n",
    "from pydantic import ValidationError\nfrom sqlalchemy import select\n",
    1,
)
start = text.index("        action_counts: Counter[str] = Counter()\n")
end = text.index("        gate = self._gate(portfolio_row, metrics)\n")
replacement = '''        action_counts: Counter[str] = Counter()
        settled_maps: set[UUID] = set()
        decision_level_briers: list[float] = []
        decision_level_losses: list[float] = []
        decision_level_clvs: list[float] = []
        map_forecasts: dict[UUID, dict[str, float | None]] = {}
        first_settled_position_by_map: dict[UUID, UUID] = {}
        for position, _ in position_pairs:
            if (
                position.status in {"WON", "LOST"}
                and position.canonical_map_id not in first_settled_position_by_map
            ):
                first_settled_position_by_map[position.canonical_map_id] = position.ai_decision_id

        map_clvs: list[float] = []
        for decision_record, snapshot, series, result, evaluation in decision_rows:
            try:
                decision = AiDecision.model_validate(decision_record.normalized_response)
            except ValidationError:
                continue
            action_counts[decision.action] += 1
            if (
                result is None
                or result.provider_conflict
                or result.winner_team_id is None
                or snapshot.canonical_map_id is None
            ):
                continue
            map_id = snapshot.canonical_map_id
            settled_maps.add(map_id)
            if evaluation is not None:
                if evaluation.brier_score is not None:
                    decision_level_briers.append(float(evaluation.brier_score))
                if evaluation.log_loss is not None:
                    decision_level_losses.append(float(evaluation.log_loss))
                if evaluation.clv is not None:
                    decision_level_clvs.append(float(evaluation.clv))
                    if first_settled_position_by_map.get(map_id) == decision_record.id:
                        map_clvs.append(float(evaluation.clv))
            team_a_won = result.winner_team_id == series.team_a_id
            market_probability = _market_probability_a(
                snapshot.canonical_payload,
                team_a_id=series.team_a_id,
                team_b_id=series.team_b_id,
            )
            market_brier = brier_score(market_probability, team_a_won)
            market_loss = log_loss(market_probability, team_a_won)
            if map_id not in map_forecasts:
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

        map_briers = [
            float(row["ai_brier"])
            for row in map_forecasts.values()
            if row["ai_brier"] is not None
        ]
        map_losses = [
            float(row["ai_log_loss"])
            for row in map_forecasts.values()
            if row["ai_log_loss"] is not None
        ]
        comparable = [
            row
            for row in map_forecasts.values()
            if row["ai_brier"] is not None
            and row["ai_log_loss"] is not None
            and row["market_brier"] is not None
            and row["market_log_loss"] is not None
        ]
        comparable_ai_briers = [float(row["ai_brier"]) for row in comparable]
        comparable_ai_losses = [float(row["ai_log_loss"]) for row in comparable]
        market_briers = [float(row["market_brier"]) for row in comparable]
        market_losses = [float(row["market_log_loss"]) for row in comparable]

        avg_brier = _average(map_briers)
        avg_loss = _average(map_losses)
        avg_clv = _average(map_clvs)
        ai_brier_comparable = _average(comparable_ai_briers)
        ai_loss_comparable = _average(comparable_ai_losses)
        market_brier = _average(market_briers)
        market_loss = _average(market_losses)
        brier_improvement = _difference(market_brier, ai_brier_comparable)
        log_loss_improvement = _difference(market_loss, ai_loss_comparable)

        risk_adjusted_return = None
        if portfolio_row["max_drawdown_pct"] and portfolio_row["max_drawdown_pct"] > 0:
            risk_adjusted_return = portfolio_row["roi"] / portfolio_row["max_drawdown_pct"]

        metrics = {
            "sample_policy": {
                "prediction": "FIRST_SUCCESSFUL_DECISION_PER_MAP",
                "clv": "FIRST_SETTLED_POSITION_PER_MAP",
                "portfolio": "ALL_EXECUTED_POSITIONS",
            },
            "settled_maps": len(settled_maps),
            "successful_decisions": len(decision_rows),
            "action_counts": dict(sorted(action_counts.items())),
            "prediction_sample_count": len(map_briers),
            "average_brier_score": avg_brier,
            "average_log_loss": avg_loss,
            "average_clv": avg_clv,
            "clv_sample_count": len(map_clvs),
            "market_comparison": {
                "sample_count": len(comparable),
                "market_average_brier_score": market_brier,
                "ai_average_brier_score": ai_brier_comparable,
                "brier_improvement_vs_market": brier_improvement,
                "market_average_log_loss": market_loss,
                "ai_average_log_loss": ai_loss_comparable,
                "log_loss_improvement_vs_market": log_loss_improvement,
            },
            "decision_level": {
                "prediction_sample_count": len(decision_level_briers),
                "average_brier_score": _average(decision_level_briers),
                "average_log_loss": _average(decision_level_losses),
                "average_clv": _average(decision_level_clvs),
                "clv_sample_count": len(decision_level_clvs),
            },
            "average_stake_pct_of_available_cash": _average(stake_ratios),
            "largest_stake_pct_of_available_cash": max(stake_ratios, default=None),
            "longest_losing_streak": losing_streak,
            "risk_adjusted_return_over_max_drawdown": risk_adjusted_return,
        }
'''
text = text[:start] + replacement + text[end:]
quality.write_text(text, encoding="utf-8")

# Add a repeated-checkpoint regression: three decision-level forecasts across two maps
# must still expose only two independent map-level prediction samples.
test = Path("tests/test_tournament_quality.py")
text = test.read_text(encoding="utf-8")
needle = '''            evaluation.clv = 0.02
            current_bankroll += Decimal("900.00")

        report = await quality.build_report(session, canonical_event_id=event.id)
'''
replacement = '''            evaluation.clv = 0.02
            if index == 1:
                extra_snapshot = DecisionSnapshotRecord(
                    id=uuid4(),
                    canonical_map_id=canonical_map.id,
                    decision_at=snapshot.decision_at + timedelta(minutes=5),
                    created_at=snapshot.decision_at + timedelta(minutes=5),
                    mode="LIVE_BASIC",
                    canonical_payload=snapshot.canonical_payload,
                    snapshot_hash=f"quality-extra-{uuid4()}",
                )
                session.add(extra_snapshot)
                await session.flush()
                extra_decision = _no_buy_decision(extra_snapshot)
                session.add(extra_decision)
                await session.flush()
                assert await EvaluationService().evaluate_snapshot(
                    session,
                    snapshot_id=extra_snapshot.id,
                ) == 1
            current_bankroll += Decimal("900.00")

        report = await quality.build_report(session, canonical_event_id=event.id)
'''
if needle not in text:
    raise SystemExit("quality test insertion point not found")
text = text.replace(needle, replacement, 1)
needle = '''        assert experiment["quality"]["settled_maps"] == 2
        assert experiment["quality"]["average_clv"] == pytest.approx(0.02)
'''
replacement = '''        assert experiment["quality"]["settled_maps"] == 2
        assert experiment["quality"]["successful_decisions"] == 3
        assert experiment["quality"]["prediction_sample_count"] == 2
        assert experiment["quality"]["decision_level"]["prediction_sample_count"] == 3
        assert experiment["quality"]["sample_policy"]["portfolio"] == "ALL_EXECUTED_POSITIONS"
        assert experiment["quality"]["average_clv"] == pytest.approx(0.02)
'''
if needle not in text:
    raise SystemExit("quality test assertion point not found")
text = text.replace(needle, replacement, 1)
text += '''\n\ndef _no_buy_decision(snapshot: DecisionSnapshotRecord) -> AiDecisionRecord:\n    provider, model, prompt, policy, view = EXPERIMENT\n    return AiDecisionRecord(\n        snapshot_id=snapshot.id,\n        snapshot_hash=snapshot.snapshot_hash,\n        provider=provider,\n        model=model,\n        model_version=model,\n        prompt_version=prompt,\n        decision_policy_version=policy,\n        ai_view_version=view,\n        ai_input_hash=f"quality-no-buy-{uuid4()}",\n        bankroll_before=Decimal("10900.00"),\n        stake=None,\n        request_started_at=snapshot.decision_at,\n        response_received_at=snapshot.decision_at + timedelta(seconds=1),\n        latency_seconds=1.0,\n        normalized_response={\n            "action": "NO_BUY",\n            "fair_probability_a": 0.62,\n            "confidence": 0.65,\n            "market_assessment": "FAIR",\n            "minimum_acceptable_odds_a": None,\n            "stake": None,\n            "primary_reasons": ["repeated checkpoint fixture"],\n            "blockers": [],\n        },\n        raw_response={"fixture": True},\n        parse_status="SUCCESS",\n    )\n'''
test.write_text(text, encoding="utf-8")
