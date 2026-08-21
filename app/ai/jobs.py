"""Durable-job scheduling rules for per-provider AI decisions.

One DecisionSnapshot fans out to one ``RUN_AI_PROVIDER`` durable job per
configured (provider, model) experiment.  The dedupe key is version-scoped on
the full experiment identity so prompt/policy/ai-view upgrades always re-run
without old succeeded jobs hiding the new version.
"""

from uuid import UUID

from app.ai.base import ai_decision_lane_key

_AI_JOB_PREFIX = "ai"


def ai_job_dedupe_key(snapshot_hash: str, provider: str, model: str) -> str:
    return ai_job_dedupe_key_for_experiment(
        snapshot_hash,
        ai_decision_lane_key(provider, model),
    )


def ai_job_dedupe_key_for_experiment(
    snapshot_hash: str,
    experiment: tuple[str, str, str, str, str],
) -> str:
    provider, model, prompt_version, decision_policy_version, ai_view_version = experiment
    return (
        f"{_AI_JOB_PREFIX}:{snapshot_hash}:{provider}:{model}:"
        f"{prompt_version}:{decision_policy_version}:{ai_view_version}"
    )


def ai_job_payload(snapshot_id: UUID, provider: str, model: str) -> dict:
    return {
        "snapshot_id": str(snapshot_id),
        "provider": provider,
        "model": model,
    }


def ai_job_priority(snapshot_mode: str | None) -> int:
    """Claim ordering uses ascending priority, so live jobs win.

    Reconciliation backfills stay at 150 and therefore yield to every trigger
    path below it, including historical snapshots that re-entered the queue.
    """
    return {
        "LIVE_FULL": 40,
        "LIVE_BASIC": 40,
        "POST_DRAFT": 70,
        "DRAFT": 70,
        "PREMATCH": 90,
    }.get((snapshot_mode or "").upper(), 50)
