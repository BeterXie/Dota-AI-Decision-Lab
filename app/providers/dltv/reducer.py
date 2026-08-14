from app.canonical import content_digest
from app.domain.live import DltvFastPatch, DltvFastState, DltvReduction

STATE_FIELDS = (
    "game_time_seconds",
    "radiant_kills",
    "dire_kills",
    "radiant_nw_lead",
    "first_blood",
    "canvas",
    "charts",
)


def reduce_fast_state(
    previous: DltvFastState | None,
    patch: DltvFastPatch,
    *,
    map_reset: bool = False,
) -> DltvReduction:
    if previous is not None and previous.valve_match_id != patch.valve_match_id:
        raise ValueError("DLTV patch and effective state belong to different maps")

    values = {
        field: getattr(previous, field) if previous is not None else None for field in STATE_FIELDS
    }
    warnings: list[str] = []
    for field, value in patch.updates.items():
        if field not in STATE_FIELDS:
            continue
        if (
            field == "game_time_seconds"
            and isinstance(value, int)
            and previous is not None
            and previous.game_time_seconds is not None
            and value < previous.game_time_seconds
            and not map_reset
        ):
            warnings.append("DLTV_GAME_TIME_REGRESSION")
            continue
        values[field] = value

    state_hash = content_digest(values)
    changed = bool(patch.updates) and (previous is None or state_hash != previous.state_hash)
    if previous is None and not patch.updates:
        return DltvReduction(state=None, changed=False, duplicate=True)
    state_changed_at = (
        patch.message_received_at
        if changed or previous is None
        else previous.last_state_change_received_at
    )
    source_game_time = values["game_time_seconds"]
    state = DltvFastState(
        valve_match_id=patch.valve_match_id,
        **values,
        source_game_time=source_game_time if isinstance(source_game_time, int) else None,
        last_message_received_at=patch.message_received_at,
        last_state_change_received_at=state_changed_at,
        state_hash=state_hash,
        last_payload_hash=patch.payload_hash,
        connection_id=patch.connection_id,
        reconnect_generation=patch.reconnect_generation,
    )
    return DltvReduction(
        state=state,
        changed=changed,
        duplicate=not changed,
        warnings=tuple(warnings),
    )
