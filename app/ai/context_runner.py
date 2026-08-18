"""Explicit, side-effect-free-by-default runner for controlled context experiments.

This path intentionally does not fan out from normal production scheduling.  A
caller chooses a historical immutable snapshot and one registered context
profile.  Provider/model/prompt/policy stay fixed while prior-decision history
and portfolio state are isolated on the full five-part experiment identity.
"""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import DECISION_POLICY_VERSION, PROMPT_VERSION
from app.ai.context_profiles import context_profile
from app.ai.coordinator import AiCoordinator, PreparedAiDecision, _prior_from_rows
from app.ai.input import build_ai_input
from app.canonical import canonical_bytes
from app.evaluation.portfolio_models import TournamentPortfolioPositionRecord
from app.models import AiDecisionRecord, DecisionSnapshotRecord

_BASELINE_PROMPT_VERSION = "decision-analyst-v5.1-output"
_BASELINE_DECISION_POLICY_VERSION = "shadow-tournament-portfolio-v3"
_BASELINE_AI_VIEW_VERSION = "ai-view-v6"
_BASELINE_MODELS_BY_PROVIDER = {
    "openai": "gpt-5.6-terra",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-3.6-flash",
    "deepseek": "deepseek-v4-pro",
}

ExperimentKey = tuple[str, str, str, str, str]


class AiContextExperimentRunner:
    """Run one controlled context profile using existing coordinator semantics.

    The production coordinator deliberately remains unchanged.  This runner
    reuses its provider invocation, validation, bankroll formatting and
    portfolio service, but makes experiment selection explicit and exact.
    """

    def __init__(self, coordinator: AiCoordinator) -> None:
        self._coordinator = coordinator

    async def prepare(
        self,
        session: AsyncSession,
        snapshot,
        *,
        provider: str,
        model: str,
        ai_view_version: str,
        job_enqueued_at: datetime | None = None,
        job_claimed_at: datetime | None = None,
    ) -> PreparedAiDecision:
        self._validate_controlled_identity(provider, model, ai_view_version)
        candidate = self._coordinator.get_provider(provider, model)
        experiment: ExperimentKey = (
            provider,
            model,
            PROMPT_VERSION,
            DECISION_POLICY_VERSION,
            ai_view_version,
        )
        input_prepare_started_at = datetime.now(UTC)
        existing_record = await session.scalar(
            select(AiDecisionRecord).where(
                AiDecisionRecord.snapshot_id == snapshot.snapshot_id,
                AiDecisionRecord.provider == provider,
                AiDecisionRecord.model == model,
                AiDecisionRecord.prompt_version == PROMPT_VERSION,
                AiDecisionRecord.decision_policy_version == DECISION_POLICY_VERSION,
                AiDecisionRecord.ai_view_version == ai_view_version,
            )
        )
        if existing_record is not None:
            return PreparedAiDecision(
                provider=candidate,
                snapshot=snapshot,
                provider_input="",
                ai_input_hash=existing_record.ai_input_hash or "",
                bankroll_before=float(existing_record.bankroll_before or 0.0),
                input_prepare_started_at=input_prepare_started_at,
                input_prepare_completed_at=datetime.now(UTC),
                existing_record=existing_record,
                job_enqueued_at=job_enqueued_at,
                job_claimed_at=job_claimed_at,
            )

        snapshot_record = await session.get(DecisionSnapshotRecord, snapshot.snapshot_id)
        canonical_map_id = snapshot_record.canonical_map_id if snapshot_record is not None else None
        prior = await self._exact_prior_decisions(
            session,
            canonical_map_id=canonical_map_id,
            snapshot=snapshot,
            experiment=experiment,
        )
        portfolio = self._coordinator._portfolio
        portfolio_scope = (
            await portfolio.scope_for_snapshot(session, snapshot.snapshot_id)
            if portfolio is not None
            else None
        )
        portfolio_context = (
            await portfolio.context_for_scope(
                session,
                scope=portfolio_scope,
                experiment=experiment,
                funding_reference_at=snapshot.decision_at,
            )
            if portfolio is not None and portfolio_scope is not None
            else None
        )
        bankroll_context = self._coordinator._bankroll_context(
            prior,
            portfolio_context=portfolio_context,
        )
        base_input = build_ai_input(
            snapshot,
            ai_view_version=ai_view_version,
            max_live_data_lag_seconds=self._coordinator._max_live_data_lag_seconds,
        )
        provider_input_bytes = canonical_bytes(
            self._coordinator._provider_input(base_input, bankroll_context)
        )
        return PreparedAiDecision(
            provider=candidate,
            snapshot=snapshot,
            provider_input=provider_input_bytes.decode("utf-8"),
            ai_input_hash=hashlib.sha256(provider_input_bytes).hexdigest(),
            bankroll_before=float(bankroll_context["bankroll_before"]),
            input_prepare_started_at=input_prepare_started_at,
            input_prepare_completed_at=datetime.now(UTC),
            existing_record=None,
            job_enqueued_at=job_enqueued_at,
            job_claimed_at=job_claimed_at,
            portfolio_scope=portfolio_scope,
        )

    async def run(
        self,
        session: AsyncSession,
        snapshot,
        *,
        provider: str,
        model: str,
        ai_view_version: str,
    ) -> AiDecisionRecord:
        """Run and persist one explicit context experiment in caller transaction."""
        prepared = await self.prepare(
            session,
            snapshot,
            provider=provider,
            model=model,
            ai_view_version=ai_view_version,
        )
        if prepared.existing_record is not None:
            return prepared.existing_record

        record = await self._coordinator.run_inference(prepared)
        # run_inference deliberately writes the production global view version;
        # the explicit experiment identity replaces it before persistence.
        record.ai_view_version = ai_view_version
        record.decision_persisted_at = datetime.now(UTC)
        session.add(record)
        await session.flush()
        portfolio = self._coordinator._portfolio
        if portfolio is not None:
            await portfolio.record_decision_position(
                session,
                record,
                scope=prepared.portfolio_scope,
            )
        return record

    async def _exact_prior_decisions(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        snapshot,
        experiment: ExperimentKey,
    ):
        if canonical_map_id is None:
            return []
        provider, model, prompt_version, policy_version, ai_view_version = experiment
        rows = (
            await session.execute(
                select(
                    AiDecisionRecord,
                    DecisionSnapshotRecord.decision_at,
                    DecisionSnapshotRecord.mode,
                    TournamentPortfolioPositionRecord.status,
                    TournamentPortfolioPositionRecord.rejection_reason,
                    TournamentPortfolioPositionRecord.cash_before,
                )
                .join(
                    DecisionSnapshotRecord,
                    DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,
                )
                .outerjoin(
                    TournamentPortfolioPositionRecord,
                    TournamentPortfolioPositionRecord.ai_decision_id == AiDecisionRecord.id,
                )
                .where(
                    DecisionSnapshotRecord.canonical_map_id == canonical_map_id,
                    DecisionSnapshotRecord.decision_at < snapshot.decision_at,
                    AiDecisionRecord.provider == provider,
                    AiDecisionRecord.model == model,
                    AiDecisionRecord.prompt_version == prompt_version,
                    AiDecisionRecord.decision_policy_version == policy_version,
                    AiDecisionRecord.ai_view_version == ai_view_version,
                    AiDecisionRecord.parse_status == "SUCCESS",
                    AiDecisionRecord.normalized_response.is_not(None),
                )
                .order_by(
                    DecisionSnapshotRecord.decision_at.asc(),
                    AiDecisionRecord.request_started_at.asc(),
                )
            )
        ).all()
        return _prior_from_rows(list(rows))

    @staticmethod
    def _validate_controlled_identity(provider: str, model: str, ai_view_version: str) -> None:
        if context_profile(ai_view_version) is None:
            raise ValueError("context experiment runner requires a registered challenger profile")
        if PROMPT_VERSION != _BASELINE_PROMPT_VERSION:
            raise RuntimeError("context ablation v1 requires frozen baseline prompt version")
        if DECISION_POLICY_VERSION != _BASELINE_DECISION_POLICY_VERSION:
            raise RuntimeError("context ablation v1 requires frozen baseline decision policy")
        expected_model = _BASELINE_MODELS_BY_PROVIDER.get(provider)
        if expected_model is None:
            raise ValueError(f"provider has no frozen v1 context baseline: {provider}")
        if model != expected_model:
            raise ValueError(
                f"context ablation requires frozen {provider} model {expected_model}, got {model}"
            )
