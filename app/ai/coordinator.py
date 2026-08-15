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

ExperimentKey = tuple[str, str, str, str, str]


@dataclass(frozen=True)
class _PriorDecision:
    decision_at: datetime
    mode: str
    decision: AiDecision


@dataclass(frozen=True)
class PreparedAiDecision:
    """Everything required to call one provider without touching the DB.

    Runtime ``RUN_AI_PROVIDER`` jobs split into PREPARE (short DB read),
    INFERENCE (HTTP only), and PERSIST (short DB write).  The prepared object
    carries the immutable provider input plus the durable-job timestamps that
    become the latency trace on the final ``AiDecisionRecord``.
    """

    provider: AiProvider
    snapshot: DecisionSnapshot
    provider_input: str
    ai_input_hash: str
    bankroll_before: float
    input_prepare_started_at: datetime
    input_prepare_completed_at: datetime
    existing_record: AiDecisionRecord | None = None
    job_enqueued_at: datetime | None = None
    job_claimed_at: datetime | None = None


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

    @property
    def experiments(self) -> tuple[ExperimentKey, ...]:
        return tuple(
            ai_experiment_key(provider.name, provider.model) for provider in self._providers
        )

    def get_provider(self, provider: str, model: str) -> AiProvider:
        for candidate in self._providers:
            if candidate.name == provider and candidate.model == model:
                return candidate
        raise ValueError(f"AI provider experiment is not configured: {provider}/{model}")

    async def prepare(
        self,
        session: AsyncSession,
        snapshot: DecisionSnapshot,
        *,
        provider: str,
        model: str,
        job_enqueued_at: datetime | None = None,
        job_claimed_at: datetime | None = None,
    ) -> PreparedAiDecision:
        """PREPARE phase for one provider job.

        All database reads happen here, in one short transaction, and the
        session is closed again before any HTTP call starts.
        """
        candidate = self.get_provider(provider, model)
        input_prepare_started_at = datetime.now(UTC)
        base_input = build_ai_input(
            snapshot,
            max_live_data_lag_seconds=self._max_live_data_lag_seconds,
        )
        snapshot_record = await session.get(DecisionSnapshotRecord, snapshot.snapshot_id)
        canonical_map_id = snapshot_record.canonical_map_id if snapshot_record is not None else None
        experiment = ai_experiment_key(provider, model)
        existing_record = await session.scalar(
            select(AiDecisionRecord).where(
                AiDecisionRecord.snapshot_id == snapshot.snapshot_id,
                AiDecisionRecord.provider == provider,
                AiDecisionRecord.model == model,
                AiDecisionRecord.prompt_version == experiment[2],
                AiDecisionRecord.decision_policy_version == experiment[3],
                AiDecisionRecord.ai_view_version == experiment[4],
            )
        )
        prior = await self._prior_decisions(
            session,
            canonical_map_id=canonical_map_id,
            snapshot=snapshot,
            provider=provider,
            model=model,
        )
        bankroll_context = self._bankroll_context(prior)
        if existing_record is not None:
            provider_input = ""
            ai_input_hash = existing_record.ai_input_hash or ""
        else:
            provider_input_bytes = canonical_bytes(
                self._provider_input(base_input, bankroll_context)
            )
            provider_input = provider_input_bytes.decode("utf-8")
            ai_input_hash = hashlib.sha256(provider_input_bytes).hexdigest()
        return PreparedAiDecision(
            provider=candidate,
            snapshot=snapshot,
            provider_input=provider_input,
            ai_input_hash=ai_input_hash,
            bankroll_before=float(bankroll_context["bankroll_before"]),
            input_prepare_started_at=input_prepare_started_at,
            input_prepare_completed_at=datetime.now(UTC),
            existing_record=existing_record,
            job_enqueued_at=job_enqueued_at,
            job_claimed_at=job_claimed_at,
        )

    async def prepare_all(
        self,
        session: AsyncSession,
        snapshot: DecisionSnapshot,
        *,
        job_enqueued_at: datetime | None = None,
        job_claimed_at: datetime | None = None,
    ) -> list[PreparedAiDecision]:
        """PREPARE phase for every configured experiment with one history query.

        This is the batch/replay convenience path.  The runtime fan-out path
        uses :meth:`prepare` so each durable job only reads its own experiment;
        both paths finish all DB work before any provider HTTP request.
        """
        if not self._providers:
            return []
        input_prepare_started_at = datetime.now(UTC)
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

        # One SQL round-trip loads every configured experiment's prior rows.
        # Python then groups them in memory instead of issuing one query per
        # provider before the HTTP fan-out starts.
        prior_by_provider_model = await self._load_prior_rows(
            session,
            canonical_map_id=canonical_map_id,
            snapshot=snapshot,
            providers=self._providers,
        )
        prepared: list[PreparedAiDecision] = []
        for provider in self._providers:
            experiment = ai_experiment_key(provider.name, provider.model)
            existing_record = existing_by_experiment.get(experiment)
            prior = prior_by_provider_model.get((provider.name, provider.model), [])
            bankroll_context = self._bankroll_context(prior)
            if existing_record is not None:
                provider_input = ""
                ai_input_hash = existing_record.ai_input_hash or ""
            else:
                provider_input_bytes = canonical_bytes(
                    self._provider_input(base_input, bankroll_context)
                )
                provider_input = provider_input_bytes.decode("utf-8")
                ai_input_hash = hashlib.sha256(provider_input_bytes).hexdigest()
            prepared.append(
                PreparedAiDecision(
                    provider=provider,
                    snapshot=snapshot,
                    provider_input=provider_input,
                    ai_input_hash=ai_input_hash,
                    bankroll_before=float(bankroll_context["bankroll_before"]),
                    input_prepare_started_at=input_prepare_started_at,
                    input_prepare_completed_at=datetime.now(UTC),
                    existing_record=existing_record,
                    job_enqueued_at=job_enqueued_at,
                    job_claimed_at=job_claimed_at,
                )
            )
        return prepared

    async def run_inference(self, prepared: PreparedAiDecision) -> AiDecisionRecord:
        """INFERENCE phase: HTTP only, no database session or transaction."""
        if prepared.existing_record is not None:
            return prepared.existing_record
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        raw_response = None
        normalized_response = None
        stake = None
        parse_status = "SUCCESS"
        error = None
        model_version = prepared.provider.model
        received_at = None
        try:
            result = await asyncio.wait_for(
                prepared.provider.decide(prepared.provider_input),
                timeout=self._timeout_seconds,
            )
            received_at = datetime.now(UTC)
            raw_response = result.raw_response
            validate_ai_decision(
                result.decision,
                bankroll_before=prepared.bankroll_before,
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
            snapshot_id=prepared.snapshot.snapshot_id,
            snapshot_hash=prepared.snapshot.snapshot_hash,
            provider=prepared.provider.name,
            model=prepared.provider.model,
            model_version=model_version,
            prompt_version=PROMPT_VERSION,
            decision_policy_version=DECISION_POLICY_VERSION,
            ai_view_version=AI_VIEW_VERSION,
            ai_input_hash=prepared.ai_input_hash,
            bankroll_before=prepared.bankroll_before,
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
            job_enqueued_at=prepared.job_enqueued_at,
            job_claimed_at=prepared.job_claimed_at,
            input_prepare_started_at=prepared.input_prepare_started_at,
            input_prepare_completed_at=prepared.input_prepare_completed_at,
        )

    async def run_all(
        self, session: AsyncSession, snapshot: DecisionSnapshot
    ) -> list[AiDecisionRecord]:
        """Batch/replay convenience API.

        The production runtime no longer calls this from a durable job: it uses
        ``prepare`` -> ``run_inference`` -> a new PERSIST transaction instead.
        This method is retained for in-process replay and tests.
        """
        prepared_jobs = await self.prepare_all(session, snapshot)
        records = await asyncio.gather(*(self.run_inference(item) for item in prepared_jobs))
        persisted_at = datetime.now(UTC)
        for prepared, record in zip(prepared_jobs, records, strict=True):
            if prepared.existing_record is None:
                record.decision_persisted_at = persisted_at
                session.add(record)
        await session.flush()
        return records

    async def _prior_decisions(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        snapshot: DecisionSnapshot,
        provider: str,
        model: str,
    ) -> list[_PriorDecision]:
        rows = await self._prior_rows(
            session,
            canonical_map_id=canonical_map_id,
            snapshot=snapshot,
            provider=provider,
            model=model,
        )
        return _prior_from_rows(rows)

    async def _load_prior_rows(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        snapshot: DecisionSnapshot,
        providers: list[AiProvider],
    ) -> dict[tuple[str, str], list[_PriorDecision]]:
        if canonical_map_id is None or not providers:
            return {}
        provider_names = tuple({item.name for item in providers})
        models = tuple({item.model for item in providers})
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
                    AiDecisionRecord.provider.in_(provider_names),
                    AiDecisionRecord.model.in_(models),
                    AiDecisionRecord.parse_status == "SUCCESS",
                    AiDecisionRecord.normalized_response.is_not(None),
                )
                .order_by(
                    DecisionSnapshotRecord.decision_at.asc(),
                    AiDecisionRecord.request_started_at.asc(),
                )
            )
        ).all()
        by_provider_model: dict[tuple[str, str], list[tuple]] = {}
        for record, decision_at, mode in rows:
            by_provider_model.setdefault((record.provider, record.model), []).append(
                (record, decision_at, mode)
            )
        return {
            key: _prior_from_rows(value)
            for key, value in by_provider_model.items()
        }

    async def _prior_rows(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        snapshot: DecisionSnapshot,
        provider: str,
        model: str,
    ) -> list[tuple[AiDecisionRecord, datetime, str]]:
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
                    AiDecisionRecord.provider == provider,
                    AiDecisionRecord.model == model,
                    AiDecisionRecord.parse_status == "SUCCESS",
                    AiDecisionRecord.normalized_response.is_not(None),
                )
                .order_by(
                    DecisionSnapshotRecord.decision_at.asc(),
                    AiDecisionRecord.request_started_at.asc(),
                )
            )
        ).all()
        return list(rows)

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
            # Accounting covers every canonical prior round. Only the most
            # recent rounds are shown to the model, keeping token usage and
            # bankroll correctness as two independent controls.
            "prior_decisions": prior_decisions[-self._prior_decisions_limit :],
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


def _prior_from_rows(
    rows: list[tuple[AiDecisionRecord, datetime, str]],
) -> list[_PriorDecision]:
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
    # All prior rounds are returned for bankroll accounting. Trimming to
    # the prompt-context window happens later in _bankroll_context, so a
    # smaller history limit can never make earlier stakes "reappear".
    return prior
