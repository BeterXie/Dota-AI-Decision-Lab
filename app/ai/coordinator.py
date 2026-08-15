import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import (
    AI_VIEW_VERSION,
    DECISION_POLICY_VERSION,
    PROMPT_VERSION,
    AiProvider,
    AiProviderFailure,
    ai_experiment_key,
    validate_ai_decision,
)
from app.ai.input import build_ai_input
from app.canonical import canonical_bytes
from app.domain.decision import AiDecision
from app.domain.snapshot import DecisionSnapshot
from app.models import AiDecisionRecord, DecisionSnapshotRecord


@dataclass(frozen=True)
class _PriorDecision:
    decision_at: datetime
    mode: str
    decision: AiDecision


class AiCoordinator:
    def __init__(
        self,
        providers: list[AiProvider],
        *,
        timeout_seconds: float,
        max_live_data_lag_seconds: float = 120.0,
        virtual_bankroll: float = 10_000.0,
        prior_decisions_limit: int = 10,
    ) -> None:
        if virtual_bankroll <= 0:
            raise ValueError("virtual_bankroll must be positive")
        if prior_decisions_limit < 1:
            raise ValueError("prior_decisions_limit must be at least 1")
        self._providers = providers
        self._timeout_seconds = timeout_seconds
        self._max_live_data_lag_seconds = max_live_data_lag_seconds
        self._virtual_bankroll = round(float(virtual_bankroll), 2)
        self._prior_decisions_limit = prior_decisions_limit

    async def run_all(
        self, session: AsyncSession, snapshot: DecisionSnapshot
    ) -> list[AiDecisionRecord]:
        base_input = build_ai_input(
            snapshot,
            max_live_data_lag_seconds=self._max_live_data_lag_seconds,
        )
        snapshot_record = await session.get(DecisionSnapshotRecord, snapshot.snapshot_id)
        canonical_map_id = snapshot_record.canonical_map_id if snapshot_record is not None else None
        existing = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(
                        AiDecisionRecord.snapshot_id == snapshot.snapshot_id
                    )
                )
            ).all()
        )
        existing_by_experiment = {
            (
                record.provider,
                record.model,
                record.prompt_version,
                record.decision_policy_version,
                record.ai_view_version,
            ): record
            for record in existing
        }

        # Load provider-scoped context sequentially: a single AsyncSession must
        # not run concurrent queries. Provider HTTP calls still fan out below.
        jobs: list[tuple[AiProvider, AiDecisionRecord | None, str, str, float]] = []
        for provider in self._providers:
            experiment = ai_experiment_key(provider.name, provider.model)
            existing_record = existing_by_experiment.get(experiment)
            if existing_record is not None:
                jobs.append((provider, existing_record, "", "", 0.0))
                continue
            prior = await self._prior_decisions(
                session,
                canonical_map_id=canonical_map_id,
                snapshot=snapshot,
                provider=provider,
            )
            bankroll_context = self._bankroll_context(prior)
            provider_input_bytes = canonical_bytes(
                self._provider_input(base_input, bankroll_context)
            )
            jobs.append(
                (
                    provider,
                    None,
                    provider_input_bytes.decode("utf-8"),
                    hashlib.sha256(provider_input_bytes).hexdigest(),
                    float(bankroll_context["bankroll_before"]),
                )
            )

        async def run(
            job: tuple[AiProvider, AiDecisionRecord | None, str, str, float],
        ) -> AiDecisionRecord:
            provider, existing_record, provider_input, ai_input_hash, bankroll_before = job
            if existing_record is not None:
                return existing_record
            started_at = datetime.now(UTC)
            started_clock = perf_counter()
            raw_response = None
            normalized_response = None
            stake = None
            parse_status = "SUCCESS"
            error = None
            model_version = provider.model
            received_at = None
            try:
                result = await asyncio.wait_for(
                    provider.decide(provider_input), timeout=self._timeout_seconds
                )
                received_at = datetime.now(UTC)
                raw_response = result.raw_response
                validate_ai_decision(
                    result.decision,
                    bankroll_before=bankroll_before,
                    raw_response=raw_response,
                )
                normalized_response = result.decision.model_dump(mode="json")
                stake = result.decision.stake
                model_version = result.model_version
            except TimeoutError:
                received_at = datetime.now(UTC)
                parse_status = "TIMEOUT"
                error = f"provider exceeded {self._timeout_seconds:.1f}s timeout"
            except AiProviderFailure as exc:
                received_at = datetime.now(UTC)
                raw_response = exc.raw_response
                parse_status = exc.parse_status
                error = str(exc)
            except Exception as exc:
                received_at = datetime.now(UTC)
                parse_status = "FAILED"
                error = f"{type(exc).__name__}: {exc}"
            return AiDecisionRecord(
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                provider=provider.name,
                model=provider.model,
                model_version=model_version,
                prompt_version=PROMPT_VERSION,
                decision_policy_version=DECISION_POLICY_VERSION,
                ai_view_version=AI_VIEW_VERSION,
                ai_input_hash=ai_input_hash,
                bankroll_before=bankroll_before,
                stake=stake,
                request_started_at=started_at,
                response_received_at=received_at,
                latency_seconds=perf_counter() - started_clock,
                raw_response=(
                    to_jsonable_python(raw_response) if raw_response is not None else None
                ),
                normalized_response=normalized_response,
                parse_status=parse_status,
                error=error,
            )

        records = await asyncio.gather(*(run(job) for job in jobs))
        for record in records:
            if record not in existing:
                session.add(record)
        await session.flush()
        return records

    async def _prior_decisions(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        snapshot: DecisionSnapshot,
        provider: AiProvider,
    ) -> list[_PriorDecision]:
        if canonical_map_id is None:
            return []
        rows = (
            await session.execute(
                select(
                    AiDecisionRecord,
                    DecisionSnapshotRecord.decision_at,
                    DecisionSnapshotRecord.mode,
                )
                .join(
                    DecisionSnapshotRecord,
                    DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,
                )
                .where(
                    DecisionSnapshotRecord.canonical_map_id == canonical_map_id,
                    DecisionSnapshotRecord.decision_at < snapshot.decision_at,
                    AiDecisionRecord.provider == provider.name,
                    AiDecisionRecord.model == provider.model,
                    AiDecisionRecord.parse_status == "SUCCESS",
                    AiDecisionRecord.normalized_response.is_not(None),
                )
                .order_by(
                    DecisionSnapshotRecord.decision_at.asc(),
                    AiDecisionRecord.request_started_at.asc(),
                )
            )
        ).all()

        # One decision per checkpoint for this experiment. Version bumps can
        # leave several records on the same snapshot; keep the newest attempt
        # so the model sees one round and the bankroll counts it once.
        best_by_snapshot: dict[UUID, tuple[tuple, AiDecisionRecord, datetime, str]] = {}
        for record, decision_at, mode in rows:
            attempt = (
                record.request_started_at,
                record.prompt_version,
                record.decision_policy_version,
                record.ai_view_version,
            )
            current = best_by_snapshot.get(record.snapshot_id)
            if current is None or attempt > current[0]:
                best_by_snapshot[record.snapshot_id] = (attempt, record, decision_at, mode)

        prior: list[_PriorDecision] = []
        for _, record, decision_at, mode in sorted(
            best_by_snapshot.values(), key=lambda item: item[2]
        ):
            if record.normalized_response is None:
                continue
            try:
                decision = AiDecision.model_validate(record.normalized_response)
            except Exception:
                continue
            prior.append(
                _PriorDecision(
                    decision_at=decision_at,
                    mode=mode,
                    decision=decision,
                )
            )
        return prior[-self._prior_decisions_limit :]

    def _bankroll_context(self, prior: list[_PriorDecision]) -> dict:
        bankroll_before = self._virtual_bankroll
        prior_decisions: list[dict] = []
        for item in prior:
            stake = round(float(item.decision.stake or 0.0), 2)
            prior_decisions.append(
                {
                    "decision_at": item.decision_at.isoformat(),
                    "mode": item.mode,
                    "action": item.decision.action,
                    "fair_probability_a": item.decision.fair_probability_a,
                    "confidence": item.decision.confidence,
                    "market_assessment": item.decision.market_assessment,
                    "minimum_acceptable_odds_a": item.decision.minimum_acceptable_odds_a,
                    "stake": stake,
                    "bankroll_before": bankroll_before,
                    "bankroll_after": round(bankroll_before - stake, 2),
                    "primary_reasons": item.decision.primary_reasons,
                    "counter_arguments": item.decision.counter_arguments,
                    "data_quality_concerns": item.decision.data_quality_concerns,
                }
            )
            bankroll_before = round(bankroll_before - stake, 2)
        return {
            "initial": self._virtual_bankroll,
            "bankroll_before": bankroll_before,
            "unsettled_stakes": round(self._virtual_bankroll - bankroll_before, 2),
            "units": "virtual-units",
            "policy": (
                "Independent virtual shadow bankroll for this provider/model and match. "
                "BUY_A/BUY_B require 0 < stake <= bankroll_before; other actions require "
                "stake null/0. No real money and no automatic execution."
            ),
            "prior_decisions": prior_decisions,
        }

    @staticmethod
    def _provider_input(base_input: dict, bankroll_context: dict) -> dict:
        return {
            **base_input,
            "virtual_bankroll": {
                key: value for key, value in bankroll_context.items() if key != "prior_decisions"
            },
            "prior_decisions": bankroll_context["prior_decisions"],
        }

    async def close(self) -> None:
        await asyncio.gather(*(provider.close() for provider in self._providers))
