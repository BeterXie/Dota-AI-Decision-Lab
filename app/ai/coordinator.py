import asyncio
from datetime import UTC, datetime
from time import perf_counter

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import (
    DECISION_POLICY_VERSION,
    PROMPT_VERSION,
    AiProvider,
    AiProviderFailure,
)
from app.ai.view import build_ai_view
from app.canonical import canonical_bytes
from app.domain.snapshot import DecisionSnapshot
from app.models import AiDecisionRecord


class AiCoordinator:
    def __init__(
        self,
        providers: list[AiProvider],
        *,
        timeout_seconds: float,
        max_live_data_lag_seconds: float = 120.0,
    ) -> None:
        self._providers = providers
        self._timeout_seconds = timeout_seconds
        self._max_live_data_lag_seconds = max_live_data_lag_seconds

    async def run_all(
        self, session: AsyncSession, snapshot: DecisionSnapshot
    ) -> list[AiDecisionRecord]:
        snapshot_input = canonical_bytes(
            build_ai_view(
                snapshot,
                max_live_data_lag_seconds=self._max_live_data_lag_seconds,
            )
        ).decode("utf-8")
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
            ): record
            for record in existing
        }

        async def run(provider: AiProvider):
            experiment = (
                provider.name,
                provider.model,
                PROMPT_VERSION,
                DECISION_POLICY_VERSION,
            )
            if experiment in existing_by_experiment:
                return existing_by_experiment[experiment]
            started_at = datetime.now(UTC)
            started_clock = perf_counter()
            raw_response = None
            normalized_response = None
            parse_status = "SUCCESS"
            error = None
            model_version = provider.model
            received_at = None
            try:
                result = await asyncio.wait_for(
                    provider.decide(snapshot_input), timeout=self._timeout_seconds
                )
                received_at = datetime.now(UTC)
                raw_response = result.raw_response
                normalized_response = result.decision.model_dump(mode="json")
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

        records = await asyncio.gather(*(run(provider) for provider in self._providers))
        for record in records:
            if record not in existing:
                session.add(record)
        await session.flush()
        return records

    async def close(self) -> None:
        await asyncio.gather(*(provider.close() for provider in self._providers))
