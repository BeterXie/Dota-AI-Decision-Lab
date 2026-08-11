from dataclasses import dataclass

from app.domain.snapshot import DecisionMode, GateResult


@dataclass(frozen=True)
class GateContext:
    identity_complete: bool
    market_available: bool
    market_age_seconds: float | None
    market_max_age_seconds: float
    draft_available: bool
    draft_complete: bool
    historical_future_leak: bool
    historical_blockers: tuple[str, ...]
    historical_warnings: tuple[str, ...]
    live_available: bool
    live_age_seconds: float | None
    live_max_age_seconds: float
    live_sync_status: str | None
    live_full_available: bool = False


def evaluate_gate(context: GateContext) -> GateResult:
    blockers: list[str] = []
    warnings = list(context.historical_warnings)

    if not context.identity_complete:
        blockers.append("IDENTITY_AMBIGUOUS")
    if not context.market_available:
        blockers.append("MARKET_MISSING")
    elif (
        context.market_age_seconds is None
        or context.market_age_seconds < 0
        or context.market_age_seconds > context.market_max_age_seconds
    ):
        blockers.append("MARKET_STALE")
    if context.historical_future_leak:
        blockers.append("HISTORICAL_DATA_FUTURE_LEAK")
    blockers.extend(context.historical_blockers)

    mode = DecisionMode.PREMATCH
    if context.draft_complete:
        mode = DecisionMode.POST_DRAFT
    elif context.draft_available:
        warnings.append("DRAFT_PARTIAL")

    if context.live_available and context.draft_complete:
        if context.live_age_seconds is None or context.live_age_seconds < 0:
            warnings.append("LIVE_STALE")
        elif context.live_age_seconds > context.live_max_age_seconds:
            warnings.append("LIVE_STALE")
        elif context.live_sync_status == "SAFE":
            mode = (
                DecisionMode.LIVE_FULL if context.live_full_available else DecisionMode.LIVE_BASIC
            )
        elif context.live_sync_status in {None, "UNKNOWN"}:
            warnings.append("LIVE_SYNC_UNKNOWN")
        else:
            warnings.append("LIVE_DATA_DESYNC")

    return GateResult(
        eligible=not blockers,
        mode=mode,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
