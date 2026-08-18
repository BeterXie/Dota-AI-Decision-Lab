"""Controlled provider-input projections for context value experiments.

Production ``ai-view-v6`` is immutable. These profiles derive alternate views
from the same immutable :class:`DecisionSnapshot` so model, prompt, decision
policy and source evidence can stay fixed while one context group changes.

Historical replay uses a dedicated production-view control. Its provider-facing
match context is identical to ``ai-view-v6``; only the stored experiment label
changes. This lets replay compare context profiles under the same contemporaneous
model serving and the same neutral bankroll/prior-decision control instead of
pretending a model call made after settlement reproduces the historical runtime.

The schema-aligned challenger repairs a discovered projection mismatch: snapshot
history stores player ``base_strength``, ``recent_form`` and flattened
``player_hero_*`` fields, while production ``ai-view-v6`` looks for legacy
``recent_5/10/20`` and nested ``player_hero`` fields. We intentionally do NOT
mutate v6; ``ctx-history-schema-aligned-v1`` exposes the already-stored fields
as a new auditable experiment instead.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.ai.versions import AI_VIEW_VERSION
from app.ai.view import build_ai_view
from app.domain.snapshot import DecisionSnapshot

REPLAY_PRODUCTION_CONTEXT_VERSION = "ctx-replay-production-v1"
SCHEMA_ALIGNED_CONTEXT_VERSION = "ctx-history-schema-aligned-v1"
NO_ROSTER_CONTEXT_VERSION = "ctx-ablation-no-roster-v1"
NO_PLAYER_FORM_CONTEXT_VERSION = "ctx-ablation-no-player-form-v1"
NO_PLAYER_HERO_CONTEXT_VERSION = "ctx-ablation-no-player-hero-v1"
NO_DRAFT_CONTEXT_VERSION = "ctx-ablation-no-draft-v1"
NO_LIVE_CONTEXT_VERSION = "ctx-ablation-no-live-v1"
MARKET_ONLY_CONTEXT_VERSION = "ctx-ablation-market-only-v1"


@dataclass(frozen=True, slots=True)
class AiContextProfile:
    ai_view_version: str
    label: str
    reference_ai_view_version: str
    removed_evidence: tuple[str, ...] = ()
    schema_aligned_history: bool = True


_CONTEXT_PROFILES = {
    REPLAY_PRODUCTION_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=REPLAY_PRODUCTION_CONTEXT_VERSION,
        label="Matched replay production-view control",
        reference_ai_view_version=AI_VIEW_VERSION,
        schema_aligned_history=False,
    ),
    SCHEMA_ALIGNED_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        label="History schema aligned full context",
        reference_ai_view_version=REPLAY_PRODUCTION_CONTEXT_VERSION,
    ),
    NO_ROSTER_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=NO_ROSTER_CONTEXT_VERSION,
        label="No roster context",
        reference_ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        removed_evidence=("roster",),
    ),
    NO_PLAYER_FORM_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=NO_PLAYER_FORM_CONTEXT_VERSION,
        label="No player form context",
        reference_ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        removed_evidence=("player_form",),
    ),
    NO_PLAYER_HERO_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=NO_PLAYER_HERO_CONTEXT_VERSION,
        label="No player-hero context",
        reference_ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        removed_evidence=("player_hero",),
    ),
    NO_DRAFT_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=NO_DRAFT_CONTEXT_VERSION,
        label="No draft context",
        reference_ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        removed_evidence=("draft",),
    ),
    NO_LIVE_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=NO_LIVE_CONTEXT_VERSION,
        label="No live context",
        reference_ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        removed_evidence=("live",),
    ),
    MARKET_ONLY_CONTEXT_VERSION: AiContextProfile(
        ai_view_version=MARKET_ONLY_CONTEXT_VERSION,
        label="Market-only sanity profile",
        reference_ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        removed_evidence=("history", "draft", "live"),
    ),
}

CONTEXT_EXPERIMENT_VERSIONS = tuple(_CONTEXT_PROFILES)


def context_profile(ai_view_version: str) -> AiContextProfile | None:
    """Return profile metadata, rejecting unknown non-production versions."""
    if ai_view_version == AI_VIEW_VERSION:
        return None
    profile = _CONTEXT_PROFILES.get(ai_view_version)
    if profile is None:
        raise ValueError(f"unknown AI context profile: {ai_view_version}")
    return profile


def context_profile_metadata(ai_view_version: str) -> dict[str, Any] | None:
    profile = context_profile(ai_view_version)
    if profile is None:
        return None
    return {
        "ai_view_version": profile.ai_view_version,
        "label": profile.label,
        "reference_ai_view_version": profile.reference_ai_view_version,
        "removed_evidence": list(profile.removed_evidence),
        "schema_aligned_history": profile.schema_aligned_history,
    }


def build_context_profile_view(
    snapshot: DecisionSnapshot,
    *,
    ai_view_version: str = AI_VIEW_VERSION,
    max_live_data_lag_seconds: float = 120.0,
) -> dict[str, Any]:
    """Build production or controlled experimental AI view deterministically."""
    # Validate the requested experiment identity before touching snapshot
    # evidence. Unknown profiles therefore fail closed even if the source
    # snapshot would itself be malformed for projection.
    profile = context_profile(ai_view_version)
    base_view = build_ai_view(
        snapshot,
        max_live_data_lag_seconds=max_live_data_lag_seconds,
    )
    if profile is None:
        return base_view

    view = deepcopy(base_view)
    view["ai_view_version"] = profile.ai_view_version
    if profile.schema_aligned_history:
        raw_history = snapshot.model_dump(mode="json").get("history") or {}
        view["history"] = _schema_aligned_history_view(raw_history, base_view.get("history"))

    removed = set(profile.removed_evidence)
    if "roster" in removed:
        _remove_roster_evidence(view)
    if "player_form" in removed:
        _remove_player_form_evidence(view)
    if "player_hero" in removed:
        _remove_player_hero_evidence(view)
    if "history" in removed:
        view.pop("history", None)
    if "draft" in removed:
        view.pop("draft", None)
        view.pop("draft_live_agreement", None)
    if "live" in removed:
        view.pop("live", None)
        view.pop("draft_live_agreement", None)

    return _round_floats(view)


def _schema_aligned_history_view(
    raw_history: dict[str, Any],
    production_history: Any,
) -> dict[str, Any]:
    production = production_history if isinstance(production_history, dict) else {}
    players: list[dict[str, Any]] = []
    for key, team in (("players_a", "A"), ("players_b", "B")):
        raw_players = raw_history.get(key)
        if not isinstance(raw_players, list):
            continue
        for player in raw_players:
            if not isinstance(player, dict):
                continue
            players.append(
                {
                    "team": team,
                    "position": player.get("position"),
                    "base_strength": player.get("base_strength"),
                    "recent_form": player.get("recent_form"),
                    "recent_form_confidence": player.get("recent_form_confidence"),
                    "current_hero": player.get("current_hero"),
                    "player_hero": {
                        "adjusted_strength": player.get("player_hero_strength"),
                        "sample_size": player.get("player_hero_sample"),
                        "position_fit": player.get("position_fit"),
                        "confidence": player.get("player_hero_confidence"),
                    },
                    "knowledge_cutoff": player.get("knowledge_cutoff"),
                }
            )
    return {
        "team_a": deepcopy(production.get("team_a") or {}),
        "team_b": deepcopy(production.get("team_b") or {}),
        "players": players,
        "coverage": deepcopy(production.get("coverage") or raw_history.get("coverage") or {}),
    }


def _remove_roster_evidence(view: dict[str, Any]) -> None:
    history = _dict(view.get("history"))
    for key in ("team_a", "team_b"):
        team = _dict(history.get(key))
        for field in ("roster_stability", "exact_roster_maps", "current_roster_strength"):
            team.pop(field, None)


def _remove_player_form_evidence(view: dict[str, Any]) -> None:
    history = _dict(view.get("history"))
    for player in _players(history):
        for field in ("base_strength", "recent_form", "recent_form_confidence"):
            player.pop(field, None)


def _remove_player_hero_evidence(view: dict[str, Any]) -> None:
    history = _dict(view.get("history"))
    for player in _players(history):
        player.pop("player_hero", None)


def _players(history: dict[str, Any]) -> list[dict[str, Any]]:
    value = history.get("players")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    return value
