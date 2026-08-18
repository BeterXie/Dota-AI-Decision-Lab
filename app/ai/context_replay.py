"""Safe matched historical replay orchestration for AI context experiments.

The planner selects one already-evaluable frozen-production snapshot per settled
map, then expands requested ablations with the replay controls needed to make
context deltas interpretable. Execution is intentionally pointwise: every
profile receives the same neutral bankroll and no prior model decisions. This
isolates match context and avoids fabricating retrospective portfolio returns.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.context_profiles import (
    REPLAY_PRODUCTION_CONTEXT_VERSION,
    SCHEMA_ALIGNED_CONTEXT_VERSION,
    context_profile,
)
from app.ai.context_runner import AiContextExperimentRunner
from app.evaluation import EvaluationService
from app.models import (
    AiDecisionRecord,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    MapResultRecord,
)
from app.snapshots.repository import SnapshotRepository

FROZEN_PROMPT_VERSION = "decision-analyst-v5.1-output"
FROZEN_DECISION_POLICY_VERSION = "shadow-tournament-portfolio-v3"
FROZEN_PRODUCTION_VIEW_VERSION = "ai-view-v6"
FROZEN_MODELS_BY_PROVIDER: dict[str, str] = {
    "openai": "gpt-5.6-terra",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-3.6-flash",
    "deepseek": "deepseek-v4-pro",
}
POINTWISE_REPLAY_CONTROL_VERSION = "pointwise-neutral-bankroll-no-prior-v1"
POINTWISE_REPLAY_BANKROLL = 10_000.0


@dataclass(frozen=True, slots=True)
class ContextReplayEntry:
    canonical_map_id: UUID
    snapshot_id: UUID
    decision_at: datetime
    baseline_decision_id: UUID
    ai_view_version: str


@dataclass(frozen=True, slots=True)
class ContextReplayPlan:
    provider: str
    model: str
    requested_profiles: tuple[str, ...]
    expanded_profiles: tuple[str, ...]
    map_count: int
    potential_calls: int
    already_completed: int
    planned_calls: int
    control_version: str
    entries: tuple[ContextReplayEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [
            {
                **asdict(entry),
                "canonical_map_id": str(entry.canonical_map_id),
                "snapshot_id": str(entry.snapshot_id),
                "baseline_decision_id": str(entry.baseline_decision_id),
                "decision_at": entry.decision_at.isoformat(),
            }
            for entry in self.entries
        ]
        return payload


class ContextReplayPlanner:
    async def build_plan(
        self,
        session: AsyncSession,
        *,
        provider: str,
        profiles: Iterable[str],
        max_maps: int,
        max_calls: int,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> ContextReplayPlan:
        model = _frozen_model(provider)
        requested = _normalize_requested_profiles(profiles)
        expanded = _expand_profiles(requested)
        if max_maps < 1:
            raise ValueError("max_maps must be at least 1")
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if since is not None and until is not None and since > until:
            raise ValueError("since must not be after until")

        stmt = (
            select(
                AiDecisionRecord.id.label("baseline_decision_id"),
                DecisionSnapshotRecord.id.label("snapshot_id"),
                DecisionSnapshotRecord.canonical_map_id.label("canonical_map_id"),
                DecisionSnapshotRecord.decision_at.label("decision_at"),
            )
            .join(
                DecisionSnapshotRecord,
                DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,
            )
            .join(
                MapResultRecord,
                MapResultRecord.canonical_map_id == DecisionSnapshotRecord.canonical_map_id,
            )
            .join(
                DecisionEvaluationRecord,
                DecisionEvaluationRecord.ai_decision_id == AiDecisionRecord.id,
            )
            .where(
                DecisionSnapshotRecord.canonical_map_id.is_not(None),
                AiDecisionRecord.provider == provider,
                AiDecisionRecord.model == model,
                AiDecisionRecord.prompt_version == FROZEN_PROMPT_VERSION,
                AiDecisionRecord.decision_policy_version == FROZEN_DECISION_POLICY_VERSION,
                AiDecisionRecord.ai_view_version == FROZEN_PRODUCTION_VIEW_VERSION,
                AiDecisionRecord.parse_status == "SUCCESS",
                AiDecisionRecord.normalized_response.is_not(None),
                DecisionEvaluationRecord.brier_score.is_not(None),
                DecisionEvaluationRecord.log_loss.is_not(None),
                MapResultRecord.provider_conflict.is_(False),
                MapResultRecord.winner_team_id.is_not(None),
            )
            .order_by(DecisionSnapshotRecord.decision_at, AiDecisionRecord.request_started_at)
        )
        if since is not None:
            stmt = stmt.where(DecisionSnapshotRecord.decision_at >= since)
        if until is not None:
            stmt = stmt.where(DecisionSnapshotRecord.decision_at <= until)

        rows = list((await session.execute(stmt)).all())
        selected: list[Any] = []
        seen_maps: set[UUID] = set()
        for row in rows:
            if row.canonical_map_id in seen_maps:
                continue
            seen_maps.add(row.canonical_map_id)
            selected.append(row)
            if len(selected) >= max_maps:
                break

        snapshot_ids = [row.snapshot_id for row in selected]
        existing: set[tuple[UUID, str]] = set()
        if snapshot_ids:
            existing_rows = list(
                (
                    await session.execute(
                        select(
                            AiDecisionRecord.snapshot_id, AiDecisionRecord.ai_view_version
                        ).where(
                            AiDecisionRecord.snapshot_id.in_(snapshot_ids),
                            AiDecisionRecord.provider == provider,
                            AiDecisionRecord.model == model,
                            AiDecisionRecord.prompt_version == FROZEN_PROMPT_VERSION,
                            AiDecisionRecord.decision_policy_version
                            == FROZEN_DECISION_POLICY_VERSION,
                            AiDecisionRecord.ai_view_version.in_(expanded),
                        )
                    )
                ).all()
            )
            existing = {(row.snapshot_id, row.ai_view_version) for row in existing_rows}

        entries: list[ContextReplayEntry] = []
        already_completed = 0
        for row in selected:
            for profile in expanded:
                if (row.snapshot_id, profile) in existing:
                    already_completed += 1
                    continue
                entries.append(
                    ContextReplayEntry(
                        canonical_map_id=row.canonical_map_id,
                        snapshot_id=row.snapshot_id,
                        decision_at=row.decision_at,
                        baseline_decision_id=row.baseline_decision_id,
                        ai_view_version=profile,
                    )
                )

        potential_calls = len(selected) * len(expanded)
        if len(entries) > max_calls:
            raise ValueError(
                f"planned provider calls {len(entries)} exceed max_calls={max_calls}; "
                "reduce maps/profiles or raise the explicit cap"
            )
        return ContextReplayPlan(
            provider=provider,
            model=model,
            requested_profiles=requested,
            expanded_profiles=expanded,
            map_count=len(selected),
            potential_calls=potential_calls,
            already_completed=already_completed,
            planned_calls=len(entries),
            control_version=POINTWISE_REPLAY_CONTROL_VERSION,
            entries=tuple(entries),
        )


class ContextReplayExecutor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: AiContextExperimentRunner,
        *,
        snapshots: SnapshotRepository | None = None,
        evaluation: EvaluationService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._runner = runner
        self._snapshots = snapshots or SnapshotRepository()
        self._evaluation = evaluation or EvaluationService()

    async def execute(
        self,
        plan: ContextReplayPlan,
        *,
        confirm_calls: int,
    ) -> dict[str, Any]:
        if confirm_calls != plan.planned_calls:
            raise ValueError(
                f"confirm_calls={confirm_calls} does not match fresh plan={plan.planned_calls}"
            )
        results: list[dict[str, Any]] = []
        for entry in plan.entries:
            try:
                async with self._session_factory() as session, session.begin():
                    snapshot = await self._snapshots.get(session, entry.snapshot_id)
                    if snapshot is None:
                        raise ValueError(f"snapshot disappeared: {entry.snapshot_id}")
                    record = await self._runner.run(
                        session,
                        snapshot,
                        provider=plan.provider,
                        model=plan.model,
                        ai_view_version=entry.ai_view_version,
                        bankroll_context_override=pointwise_replay_bankroll_context(),
                        record_portfolio=False,
                    )
                    if record.parse_status != "SUCCESS" or record.normalized_response is None:
                        results.append(
                            {
                                "status": "FAILED",
                                "canonical_map_id": str(entry.canonical_map_id),
                                "snapshot_id": str(entry.snapshot_id),
                                "ai_view_version": entry.ai_view_version,
                                "ai_decision_id": str(record.id),
                                "parse_status": record.parse_status,
                                "error": record.error,
                            }
                        )
                        continue
                    evaluations_created = await self._evaluation.evaluate_snapshot(
                        session,
                        snapshot_id=entry.snapshot_id,
                    )
                    results.append(
                        {
                            "status": "SUCCESS",
                            "canonical_map_id": str(entry.canonical_map_id),
                            "snapshot_id": str(entry.snapshot_id),
                            "ai_view_version": entry.ai_view_version,
                            "ai_decision_id": str(record.id),
                            "evaluations_created": evaluations_created,
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - batch replay must preserve partial progress
                results.append(
                    {
                        "status": "FAILED",
                        "canonical_map_id": str(entry.canonical_map_id),
                        "snapshot_id": str(entry.snapshot_id),
                        "ai_view_version": entry.ai_view_version,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "provider": plan.provider,
            "model": plan.model,
            "control_version": plan.control_version,
            "planned_calls": plan.planned_calls,
            "succeeded": sum(item["status"] == "SUCCESS" for item in results),
            "failed": sum(item["status"] == "FAILED" for item in results),
            "results": results,
        }


def pointwise_replay_bankroll_context() -> dict[str, Any]:
    """Fixed non-historical control shared by every matched replay profile."""
    return {
        "scope": "POINTWISE_CONTEXT_REPLAY",
        "initial": POINTWISE_REPLAY_BANKROLL,
        "bankroll_before": POINTWISE_REPLAY_BANKROLL,
        "unsettled_stakes": 0.0,
        "units": "virtual-units",
        "prior_decisions": [],
    }


def _frozen_model(provider: str) -> str:
    model = FROZEN_MODELS_BY_PROVIDER.get(provider)
    if model is None:
        supported = ", ".join(sorted(FROZEN_MODELS_BY_PROVIDER))
        raise ValueError(
            f"unsupported frozen baseline provider {provider!r}; choose one of {supported}"
        )
    return model


def _normalize_requested_profiles(profiles: Iterable[str]) -> tuple[str, ...]:
    requested: list[str] = []
    for value in profiles:
        if value == FROZEN_PRODUCTION_VIEW_VERSION:
            raise ValueError("request replay production control, not live ai-view-v6")
        context_profile(value)
        if value not in requested:
            requested.append(value)
    if not requested:
        raise ValueError("at least one context profile is required")
    return tuple(requested)


def _expand_profiles(requested: tuple[str, ...]) -> tuple[str, ...]:
    expanded: list[str] = []

    def add(value: str) -> None:
        if value not in expanded:
            expanded.append(value)

    for profile in requested:
        if profile == REPLAY_PRODUCTION_CONTEXT_VERSION:
            add(REPLAY_PRODUCTION_CONTEXT_VERSION)
            continue
        add(REPLAY_PRODUCTION_CONTEXT_VERSION)
        if profile != SCHEMA_ALIGNED_CONTEXT_VERSION:
            add(SCHEMA_ALIGNED_CONTEXT_VERSION)
        add(profile)
    return tuple(expanded)
