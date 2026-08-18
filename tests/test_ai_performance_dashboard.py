from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
)
from app.web.performance import (
    _build_experiment_groups,
    _decision_trace_payload,
    build_ai_performance_payload,
)
from app.web.premium import _map_ai_decisions_payload

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _decision(
    *,
    prompt_version: str = "prompt-v1",
    parse_status: str = "SUCCESS",
    action: str = "BUY_A",
    ai_input_hash: str = "input-hash-a",
) -> AiDecisionRecord:
    snapshot_id = uuid4()
    return AiDecisionRecord(
        id=uuid4(),
        snapshot_id=snapshot_id,
        snapshot_hash="snapshot-hash-a",
        provider="openai",
        model="gpt-test",
        model_version="gpt-test-2026-08",
        prompt_version=prompt_version,
        decision_policy_version="policy-v3",
        ai_view_version="ai-view-v2",
        ai_input_hash=ai_input_hash,
        bankroll_before=Decimal("100.00"),
        stake=Decimal("2.00") if action.startswith("BUY_") else None,
        job_enqueued_at=NOW,
        job_claimed_at=NOW + timedelta(seconds=1),
        input_prepare_started_at=NOW + timedelta(seconds=1),
        input_prepare_completed_at=NOW + timedelta(seconds=1.5),
        request_started_at=NOW + timedelta(seconds=2),
        response_received_at=NOW + timedelta(seconds=4),
        latency_seconds=2.0,
        input_tokens=1000,
        cached_input_tokens=700,
        reasoning_tokens=120,
        output_tokens=180,
        total_tokens=1180,
        decision_persisted_at=NOW + timedelta(seconds=4.5),
        normalized_response=(
            {
                "action": action,
                "fair_probability_a": 0.61,
                "confidence": 0.72,
                "market_assessment": "VALUE_A",
                "primary_reasons": ["draft edge", "market gap"],
                "blockers": [],
            }
            if parse_status == "SUCCESS"
            else None
        ),
        raw_response=None,
        parse_status=parse_status,
        error=None if parse_status == "SUCCESS" else "provider timeout",
    )


def _evaluation(
    decision: AiDecisionRecord,
    *,
    correct: bool,
    unit_pnl: str,
) -> DecisionEvaluationRecord:
    return DecisionEvaluationRecord(
        id=uuid4(),
        ai_decision_id=decision.id,
        result_correct=correct,
        brier_score=0.12,
        log_loss=0.41,
        clv=0.03,
        future_odds_direction="FAVORABLE",
        virtual_pnl=Decimal("2.40"),
        virtual_odds=Decimal("2.20"),
        unit_pnl=Decimal(unit_pnl),
        evaluated_at=NOW + timedelta(hours=1),
        metrics_version="evaluation-v3",
    )


def test_experiment_versions_are_never_merged() -> None:
    old_prompt = _decision(prompt_version="prompt-v1", ai_input_hash="input-old")
    new_prompt = _decision(prompt_version="prompt-v2", ai_input_hash="input-new")

    groups = _build_experiment_groups(
        [old_prompt, new_prompt],
        evaluation_by_decision={},
    )

    assert len(groups) == 2
    assert {item["prompt_version"] for item in groups} == {"prompt-v1", "prompt-v2"}
    assert len({item["id"] for item in groups}) == 2


def test_experiment_metrics_use_settled_buys_and_one_unit_pnl() -> None:
    correct = _decision()
    wrong = _decision(ai_input_hash="input-hash-b")
    failed = _decision(parse_status="PROVIDER_FAILED", ai_input_hash="input-hash-c")
    evaluations = {
        correct.id: _evaluation(correct, correct=True, unit_pnl="1.20"),
        wrong.id: _evaluation(wrong, correct=False, unit_pnl="-1.00"),
    }

    group = _build_experiment_groups(
        [correct, wrong, failed],
        evaluation_by_decision=evaluations,
    )[0]

    assert group["attempts"] == 3
    assert group["successful"] == 2
    assert group["failed"] == 1
    assert group["settled_buy_decisions"] == 2
    assert group["correct_buy_decisions"] == 1
    assert group["buy_accuracy"] == pytest.approx(0.5)
    assert group["unit_pnl"] == pytest.approx(0.2)
    assert group["unit_roi"] == pytest.approx(0.1)
    assert group["average_brier"] == pytest.approx(0.12)
    assert group["average_log_loss"] == pytest.approx(0.41)
    assert group["average_latency_seconds"] == pytest.approx(2.0)
    assert group["cached_input_ratio"] == pytest.approx(0.7)


def test_decision_trace_exposes_reproducible_identity_and_latency_chain() -> None:
    decision = _decision()
    snapshot = DecisionSnapshotRecord(
        id=decision.snapshot_id,
        canonical_map_id=uuid4(),
        decision_at=NOW,
        created_at=NOW,
        mode="LIVE",
        canonical_payload={"quality": {"eligible": True}},
        snapshot_hash=decision.snapshot_hash,
    )
    evaluation = _evaluation(decision, correct=True, unit_pnl="1.20")

    payload = _decision_trace_payload(
        decision,
        snapshot=snapshot,
        evaluation=evaluation,
        match_context_by_map={},
    )

    assert payload["snapshot_id"] == str(snapshot.id)
    assert payload["snapshot_hash"] == "snapshot-hash-a"
    assert payload["ai_input_hash"] == "input-hash-a"
    assert payload["prompt_version"] == "prompt-v1"
    assert payload["decision_policy_version"] == "policy-v3"
    assert payload["ai_view_version"] == "ai-view-v2"
    assert payload["primary_reasons"] == ["draft edge", "market gap"]
    assert payload["trace"]["queue_seconds"] == pytest.approx(1.0)
    assert payload["trace"]["input_prepare_seconds"] == pytest.approx(0.5)
    assert payload["trace"]["provider_latency_seconds"] == pytest.approx(2.0)
    assert payload["trace"]["end_to_end_seconds"] == pytest.approx(4.5)
    assert payload["tokens"]["cached_input"] == 700
    assert payload["evaluation"]["unit_pnl"] == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_performance_query_pages_without_loading_raw_response() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first = _decision(prompt_version="prompt-v1")
    second = _decision(prompt_version="prompt-v2", ai_input_hash="input-hash-b")
    second.snapshot_id = first.snapshot_id
    second.snapshot_hash = first.snapshot_hash
    first.raw_response = {"provider_payload": "large-private-response"}
    second.raw_response = {"provider_payload": "large-private-response"}
    snapshot = DecisionSnapshotRecord(
        id=first.snapshot_id,
        canonical_map_id=None,
        decision_at=NOW,
        created_at=NOW,
        mode="PREMATCH",
        canonical_payload={},
        snapshot_hash=first.snapshot_hash,
    )
    async with factory.begin() as session:
        session.add_all((snapshot, first, second))

    statements: list[str] = []

    def capture(*args) -> None:
        statement = args[2]
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with factory() as session:
            payload = await build_ai_performance_payload(session, limit=1)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    decision_select = next(
        statement for statement in statements if "FROM ai_decisions" in statement
    )
    assert "raw_response" not in decision_select
    assert payload["pagination"] == {
        "limit": 1,
        "offset": 0,
        "returned": 1,
        "has_more": True,
        "next_offset": 1,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_premium_ai_projection_skips_unrelated_map_detail_tables() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        canonical_map = CanonicalMap()
        session.add(canonical_map)
        await session.flush()

    statements: list[str] = []

    def capture(*args) -> None:
        statement = args[2]
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with factory() as session:
            payload = await _map_ai_decisions_payload(session, canonical_map)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)

    assert payload["latest_snapshot"] is None
    assert len(statements) == 1
    assert "FROM decision_snapshots" in statements[0]
    await engine.dispose()


@pytest.mark.asyncio
async def test_public_postmatch_projection_keeps_decisions_but_drops_diagnostics() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    decision = _decision()
    assert isinstance(decision.normalized_response, dict)
    decision.normalized_response["stake"] = 2.0
    canonical_map = CanonicalMap(id=uuid4())
    snapshot = DecisionSnapshotRecord(
        id=decision.snapshot_id,
        canonical_map_id=canonical_map.id,
        decision_at=NOW,
        created_at=NOW,
        mode="LIVE",
        canonical_payload={
            "quality": {"eligible": True, "private_quality": "hidden"},
            "private_input": "hidden",
        },
        snapshot_hash=decision.snapshot_hash,
    )
    evaluation = _evaluation(decision, correct=True, unit_pnl="1.20")
    async with factory.begin() as session:
        session.add_all((canonical_map, snapshot, decision, evaluation))

    async with factory() as session:
        payload = await _map_ai_decisions_payload(session, canonical_map, public=True)

    public_decision = payload["decisions"][0]
    assert public_decision["decision"]["action"] == "BUY_A"
    assert "snapshot_hash" not in public_decision
    assert "bankroll_before" not in public_decision
    assert "stake" not in public_decision["decision"]
    assert "total_tokens" not in public_decision
    assert payload["snapshot_payload"] is None
    assert payload["future_odds"] == []
    assert payload["latest_snapshot"]["quality"] == {"eligible": True}
    await engine.dispose()
