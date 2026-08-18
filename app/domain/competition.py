from __future__ import annotations

GROUP_STAGE = "GROUP_STAGE"
PAID_STAGE = "PAID_STAGE"
UNKNOWN_STAGE = "UNKNOWN"


def classify_stage(value: str | None) -> str:
    """Classify only authoritative group-stage labels as free-access content."""

    normalized = " ".join((value or "").casefold().replace("_", " ").split())
    if not normalized:
        return UNKNOWN_STAGE
    if "group" in normalized:
        return GROUP_STAGE
    return PAID_STAGE


def is_group_stage(value: str | None) -> bool:
    return value == GROUP_STAGE
