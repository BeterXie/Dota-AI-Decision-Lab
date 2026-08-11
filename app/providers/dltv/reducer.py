from app.domain.live import DltvFastState


class DltvStateReducer:
    def __init__(self) -> None:
        self._last_hash: dict[int, str] = {}

    def changed(self, state: DltvFastState) -> bool:
        previous = self._last_hash.get(state.valve_match_id)
        if previous == state.payload_hash:
            return False
        self._last_hash[state.valve_match_id] = state.payload_hash
        return True
