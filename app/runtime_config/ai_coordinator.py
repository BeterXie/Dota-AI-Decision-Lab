from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter

from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import (
    AI_VIEW_VERSION,
    DECISION_POLICY_VERSION,
    PROMPT_VERSION,
    AiProvider,
    AiProviderFailure,
    extract_provider_usage,
    validate_ai_decision,
)
from app.ai.coordinator import AiCoordinator as StaticAiCoordinator
from app.ai.coordinator import PreparedAiDecision
from app.domain.snapshot import DecisionSnapshot
from app.models import AiDecisionRecord
from app.runtime_config.policy import ai_decision_policy_snapshot
from app.runtime_config.service import (
    SUPPORTED_AI_PROVIDERS,
    cached_active_ai_experiments,
    resolve_ai_provider,
)


class _RuntimeProviderReference:
    """Synchronous preflight reference; PREPARE resolves the real DB snapshot."""

    def __init__(self, provider: str, model: str) -> None:
        self.name = provider
        self.model = model

    async def decide(self, snapshot_input: str):
        raise RuntimeError("runtime provider reference cannot execute inference")

    async def close(self) -> None:
        return None


class RuntimeAiCoordinator(StaticAiCoordinator):
    """Hot-configurable runtime coordinator without changing replay semantics.

    Production PREPARE freezes provider/model/key/timeout plus the runtime-safe
    input policy (live-data lag and prior-context depth) into one immutable
    ``PreparedAiDecision``. Admin edits after PREPARE therefore affect only
    subsequent inference requests. Batch/replay paths retain static behavior.
    """

    @property
    def experiments(self):
        return cached_active_ai_experiments(super().experiments)

    def get_provider(self, provider: str, model: str) -> AiProvider:
        static = self._static_provider(provider, model)
        if static is not None:
            return static
        if provider in SUPPORTED_AI_PROVIDERS:
            return _RuntimeProviderReference(provider, model)
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
        fallback = self._static_provider(provider, model)
        runtime_provider = await resolve_ai_provider(
            session,
            provider,
            model,
            fallback=fallback,
        )
        policy = await ai_decision_policy_snapshot(
            session,
            fallback_max_live_data_lag_seconds=self._max_live_data_lag_seconds,
            fallback_prior_decisions_limit=self._prior_decisions_limit,
        )
        timeout_seconds = float(
            getattr(runtime_provider, "runtime_timeout_seconds", self._timeout_seconds)
        )
        frozen = StaticAiCoordinator(
            [runtime_provider],
            timeout_seconds=timeout_seconds,
            max_live_data_lag_seconds=policy.max_live_data_lag_seconds,
            virtual_bankroll=self._virtual_bankroll,
            prior_decisions_limit=policy.prior_decisions_limit,
            portfolio=self._portfolio,
        )
        return await frozen.prepare(
            session,
            snapshot,
            provider=provider,
            model=model,
            job_enqueued_at=job_enqueued_at,
            job_claimed_at=job_claimed_at,
        )

    async def run_inference(self, prepared: PreparedAiDecision) -> AiDecisionRecord:
        """Run against the timeout frozen with the provider configuration."""
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
        usage = None
        received_at = None
        timeout_seconds = float(
            getattr(prepared.provider, "runtime_timeout_seconds", self._timeout_seconds)
        )
        close_after_call = bool(getattr(prepared.provider, "runtime_config_managed", False))
        try:
            result = await asyncio.wait_for(
                prepared.provider.decide(prepared.provider_input),
                timeout=timeout_seconds,
            )
            received_at = datetime.now(UTC)
            raw_response = result.raw_response
            usage = result.usage
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
            error = f"provider exceeded {timeout_seconds:.1f}s timeout"
        except AiProviderFailure as exc:
            received_at = datetime.now(UTC)
            raw_response = exc.raw_response
            usage = extract_provider_usage(raw_response)
            parse_status = exc.parse_status
            error = str(exc)
        except Exception as exc:
            received_at = datetime.now(UTC)
            parse_status = "FAILED"
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if close_after_call:
                await prepared.provider.close()
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
            input_tokens=usage.input_tokens if usage is not None else None,
            cached_input_tokens=(usage.cached_input_tokens if usage is not None else None),
            reasoning_tokens=usage.reasoning_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            total_tokens=usage.total_tokens if usage is not None else None,
            raw_response=(to_jsonable_python(raw_response) if raw_response is not None else None),
            normalized_response=normalized_response,
            parse_status=parse_status,
            error=error,
            job_enqueued_at=prepared.job_enqueued_at,
            job_claimed_at=prepared.job_claimed_at,
            input_prepare_started_at=prepared.input_prepare_started_at,
            input_prepare_completed_at=prepared.input_prepare_completed_at,
        )

    def _static_provider(self, provider: str, model: str) -> AiProvider | None:
        for candidate in self._providers:
            if candidate.name == provider and candidate.model == model:
                return candidate
        return None
