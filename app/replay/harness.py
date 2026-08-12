import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import to_jsonable_python

from app.canonical import content_digest
from app.domain.draft import DraftValidation
from app.domain.live import DltvFastState
from app.providers.dltv.parser import parse_draft, parse_fast_patch
from app.providers.dltv.reducer import reduce_fast_state
from app.providers.raybet.parser import parse_socket_publish
from app.snapshots.gates import GateContext, evaluate_gate
from app.temporal.aligner import CalibrationSignal, estimate_synchronization
from app.time import ensure_utc


class RecordedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    provider: Literal["raybet", "dltv", "history", "system"]
    event_type: Literal[
        "RAYBET_SOCKET_ODDS",
        "DLTV_BOOTSTRAP",
        "DLTV_FAST_SOCKET",
        "HISTORICAL_SNAPSHOT",
        "DECISION_CHECKPOINT",
    ]
    received_at: datetime
    payload: dict[str, Any]


class ReplaySettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    market_max_age_seconds: float = Field(default=30.0, gt=0)
    live_max_age_seconds: float = Field(default=45.0, gt=0)
    pairing_window_seconds: float = Field(default=30.0, gt=0)
    live_sync_safe_seconds: float = Field(default=3.0, ge=0)
    live_sync_caution_seconds: float = Field(default=8.0, ge=0)
    live_sync_min_samples: int = Field(default=3, gt=0)
    significant_odds_move: float = Field(default=0.05, gt=0)
    live_nw_signal_threshold: int = Field(default=500, gt=0)


class ReplaySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_at: datetime
    mode: str
    snapshot_hash: str
    canonical_payload: dict[str, Any]


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_event_count: int
    normalized_market_updates: int
    normalized_live_updates: int
    processed_event_ids: tuple[str, ...]
    snapshots: tuple[ReplaySnapshot, ...]


class VirtualClock:
    def __init__(self) -> None:
        self._now: datetime | None = None

    @property
    def now(self) -> datetime | None:
        return self._now

    def advance_to(self, value: datetime) -> datetime:
        current = ensure_utc(value)
        if self._now is not None and current < self._now:
            raise ValueError("virtual clock cannot move backwards")
        self._now = current
        return current

    def restore(self, value: datetime | None) -> None:
        self._now = ensure_utc(value) if value is not None else None


class ReplayHarness:
    def __init__(
        self,
        canonical_map_id: UUID,
        *,
        valve_match_id: int,
        settings: ReplaySettings | None = None,
    ) -> None:
        self._canonical_map_id = canonical_map_id
        self._valve_match_id = valve_match_id
        self._settings = settings or ReplaySettings()
        self._reset()

    def replay(
        self,
        events: list[RecordedEvent],
        *,
        restart_after: int | None = None,
    ) -> ReplayResult:
        self._reset()
        ordered = sorted(
            enumerate(events),
            key=lambda item: (ensure_utc(item[1].received_at), item[0]),
        )
        for index, (_, event) in enumerate(ordered, start=1):
            self._apply(event)
            if restart_after is not None and index == restart_after:
                state = json.loads(
                    json.dumps(to_jsonable_python(self._export_state()), sort_keys=True)
                )
                self._reset()
                self._import_state(state)
        return ReplayResult(
            raw_event_count=self._raw_event_count,
            normalized_market_updates=self._market_updates,
            normalized_live_updates=self._live_updates,
            processed_event_ids=tuple(self._processed_event_ids),
            snapshots=tuple(self._snapshots),
        )

    def _reset(self) -> None:
        self._clock = VirtualClock()
        self._seen_event_ids: set[str] = set()
        self._processed_event_ids: list[str] = []
        self._raw_event_count = 0
        self._market_updates = 0
        self._live_updates = 0
        self._market: dict[int, dict[str, Any]] = {}
        self._draft: DraftValidation | None = None
        self._draft_observed_at: datetime | None = None
        self._live: DltvFastState | None = None
        self._history: dict[str, Any] | None = None
        self._raybet_signals: list[CalibrationSignal] = []
        self._dltv_signals: list[CalibrationSignal] = []
        self._snapshots: list[ReplaySnapshot] = []

    def _apply(self, event: RecordedEvent) -> None:
        received_at = self._clock.advance_to(event.received_at)
        self._raw_event_count += 1
        if event.event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(event.event_id)
        self._processed_event_ids.append(event.event_id)
        if event.event_type == "RAYBET_SOCKET_ODDS":
            self._apply_market(event.payload, received_at)
        elif event.event_type == "DLTV_BOOTSTRAP":
            self._draft = parse_draft(event.payload)
            self._draft_observed_at = received_at
            self._apply_live(event.payload, received_at)
        elif event.event_type == "DLTV_FAST_SOCKET":
            self._apply_live(event.payload, received_at)
        elif event.event_type == "HISTORICAL_SNAPSHOT":
            self._apply_history(event.payload, received_at)
        elif event.event_type == "DECISION_CHECKPOINT":
            self._snapshots.append(self._build_snapshot(received_at))

    def _apply_market(self, payload: dict[str, Any], received_at: datetime) -> None:
        for delta in parse_socket_publish(payload):
            previous = self._market.get(delta.odds_id)
            if previous is not None:
                move = abs(float(delta.price) / float(previous["price"]) - 1.0)
                if move >= self._settings.significant_odds_move or (
                    delta.raw_status != previous["raw_status"]
                ):
                    self._raybet_signals.append(CalibrationSignal(received_at, "MARKET_REPRICE"))
            self._market[delta.odds_id] = {
                "odds_id": delta.odds_id,
                "provider_match_id": delta.match_id,
                "price": str(delta.price),
                "raw_status": delta.raw_status,
                "provider_updated_at": delta.provider_updated_at,
                "received_at": received_at,
            }
            self._market_updates += 1

    def _apply_live(self, payload: dict[str, Any], received_at: datetime) -> None:
        reduction = reduce_fast_state(
            self._live,
            parse_fast_patch(
                payload,
                valve_match_id=self._valve_match_id,
                received_at=received_at,
            ),
        )
        state = reduction.state
        if state is None:
            return
        previous = self._live
        if not reduction.changed:
            return
        if previous is not None:
            kills_changed = (
                state.radiant_kills is not None
                and state.dire_kills is not None
                and previous.radiant_kills is not None
                and previous.dire_kills is not None
                and (
                    state.radiant_kills != previous.radiant_kills
                    or state.dire_kills != previous.dire_kills
                )
            )
            nw_changed = (
                state.radiant_nw_lead is not None
                and previous.radiant_nw_lead is not None
                and abs(state.radiant_nw_lead - previous.radiant_nw_lead)
                >= self._settings.live_nw_signal_threshold
            )
            if kills_changed or nw_changed:
                self._dltv_signals.append(CalibrationSignal(received_at, "LIVE_STATE_CHANGE"))
        self._live = state
        self._live_updates += 1

    def _apply_history(self, payload: dict[str, Any], received_at: datetime) -> None:
        cutoff = _parse_datetime(payload.get("knowledge_cutoff"))
        if cutoff is None:
            raise ValueError("historical replay event requires knowledge_cutoff")
        self._history = {
            "knowledge_cutoff": cutoff,
            "first_usable_at": received_at,
            "features": deepcopy(payload.get("features", {})),
            "blockers": list(payload.get("blockers", [])),
            "warnings": list(payload.get("warnings", [])),
        }

    def _build_snapshot(self, decision_at: datetime) -> ReplaySnapshot:
        latest_market_at = max(
            (item["received_at"] for item in self._market.values()), default=None
        )
        market_age = _age_seconds(decision_at, latest_market_at)
        live_age = _age_seconds(
            decision_at,
            self._live.last_state_change_received_at if self._live is not None else None,
        )
        live_message_age = _age_seconds(
            decision_at,
            self._live.last_message_received_at if self._live is not None else None,
        )
        estimate = estimate_synchronization(
            self._canonical_map_id,
            self._raybet_signals,
            self._dltv_signals,
            calculated_at=decision_at,
            pairing_window_seconds=self._settings.pairing_window_seconds,
            safe_seconds=self._settings.live_sync_safe_seconds,
            caution_seconds=self._settings.live_sync_caution_seconds,
            min_samples=self._settings.live_sync_min_samples,
        )
        history_cutoff = self._history["knowledge_cutoff"] if self._history else None
        gate = evaluate_gate(
            GateContext(
                identity_complete=True,
                market_available=bool(self._market),
                market_pair_valid=bool(self._market),
                market_blockers=(),
                market_warnings=("MARKET_STATUS_UNKNOWN",) if self._market else (),
                market_age_seconds=market_age,
                market_max_age_seconds=self._settings.market_max_age_seconds,
                draft_available=self._draft is not None,
                draft_complete=bool(self._draft and self._draft.complete),
                historical_future_leak=bool(
                    history_cutoff is not None and history_cutoff > decision_at
                ),
                historical_blockers=tuple(self._history["blockers"] if self._history else ()),
                historical_warnings=tuple(self._history["warnings"] if self._history else ()),
                live_available=self._live is not None,
                live_message_age_seconds=live_message_age,
                live_age_seconds=live_age,
                live_max_age_seconds=self._settings.live_max_age_seconds,
                live_sync_status=estimate.status,
                live_sync_confidence=estimate.confidence,
            )
        )
        live_payload = None
        if gate.mode.value.startswith("LIVE") and self._live is not None:
            live_payload = self._live.model_dump(mode="json")
        payload = to_jsonable_python(
            {
                "schema_version": "decision-snapshot-v1",
                "decision_at": decision_at,
                "mode": gate.mode.value,
                "identity": {
                    "canonical_map_id": str(self._canonical_map_id),
                    "valve_match_id": self._valve_match_id,
                },
                "market": {
                    "observations": [
                        to_jsonable_python(self._market[key]) for key in sorted(self._market)
                    ],
                    "age_seconds": market_age,
                },
                "draft": (
                    {
                        **self._draft.model_dump(mode="json"),
                        "observed_at": self._draft_observed_at,
                    }
                    if self._draft is not None
                    else None
                ),
                "history": (
                    to_jsonable_python(self._history)
                    if self._history is not None
                    else {"status": "UNKNOWN"}
                ),
                "live": live_payload,
                "quality": {
                    "eligible": gate.eligible,
                    "blockers": list(gate.blockers),
                    "warnings": list(gate.warnings),
                    "live_message_age_seconds": live_message_age,
                    "live_effective_state_age_seconds": live_age,
                    "live_sync": estimate.model_dump(mode="json"),
                },
            }
        )
        return ReplaySnapshot(
            decision_at=decision_at,
            mode=gate.mode.value,
            snapshot_hash=content_digest(payload),
            canonical_payload=payload,
        )

    def _export_state(self) -> dict[str, Any]:
        return {
            "clock": self._clock.now,
            "seen_event_ids": sorted(self._seen_event_ids),
            "processed_event_ids": list(self._processed_event_ids),
            "raw_event_count": self._raw_event_count,
            "market_updates": self._market_updates,
            "live_updates": self._live_updates,
            "market": self._market,
            "draft": self._draft.model_dump(mode="json") if self._draft else None,
            "draft_observed_at": self._draft_observed_at,
            "live": self._live.model_dump(mode="json") if self._live else None,
            "history": self._history,
            "raybet_signals": [signal.__dict__ for signal in self._raybet_signals],
            "dltv_signals": [signal.__dict__ for signal in self._dltv_signals],
            "snapshots": [snapshot.model_dump(mode="json") for snapshot in self._snapshots],
        }

    def _import_state(self, state: dict[str, Any]) -> None:
        self._clock.restore(_parse_datetime(state.get("clock")))
        self._seen_event_ids = set(state["seen_event_ids"])
        self._processed_event_ids = list(state["processed_event_ids"])
        self._raw_event_count = int(state["raw_event_count"])
        self._market_updates = int(state["market_updates"])
        self._live_updates = int(state["live_updates"])
        self._market = {
            int(key): {
                **value,
                "provider_updated_at": _parse_datetime(value.get("provider_updated_at")),
                "received_at": _required_datetime(value.get("received_at")),
            }
            for key, value in state["market"].items()
        }
        self._draft = DraftValidation.model_validate(state["draft"]) if state["draft"] else None
        self._draft_observed_at = _parse_datetime(state.get("draft_observed_at"))
        self._live = DltvFastState.model_validate(state["live"]) if state["live"] else None
        self._history = state["history"]
        if self._history is not None:
            self._history["knowledge_cutoff"] = _required_datetime(
                self._history["knowledge_cutoff"]
            )
            self._history["first_usable_at"] = _required_datetime(self._history["first_usable_at"])
        self._raybet_signals = [
            CalibrationSignal(_required_datetime(item["received_at"]), item["event_type"])
            for item in state["raybet_signals"]
        ]
        self._dltv_signals = [
            CalibrationSignal(_required_datetime(item["received_at"]), item["event_type"])
            for item in state["dltv_signals"]
        ]
        self._snapshots = [ReplaySnapshot.model_validate(item) for item in state["snapshots"]]


def _age_seconds(now: datetime, observed_at: datetime | None) -> float | None:
    return (now - observed_at).total_seconds() if observed_at is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str):
        try:
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _required_datetime(value: object) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError("replay state contains an invalid datetime")
    return parsed
