from __future__ import annotations

from collections import deque
from time import monotonic


class PairingAttemptLimiter:
    """Small in-process limiter for bot pairing commands.

    Pairing codes already carry 96 bits of entropy; this limiter adds online
    abuse resistance without coupling chat transports to the login challenge
    tables. A process restart clears the counters, which is acceptable because
    the code space itself remains impractical to brute-force.
    """

    def __init__(self, *, max_attempts: int = 8, window_seconds: float = 300.0) -> None:
        if max_attempts <= 0 or window_seconds <= 0:
            raise ValueError("pairing limiter values must be positive")
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = monotonic()
        attempts = self._attempts.setdefault(key, deque())
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self._max_attempts:
            return False
        attempts.append(now)
        if len(self._attempts) > 2048:
            self._prune(cutoff)
        return True

    def _prune(self, cutoff: float) -> None:
        stale: list[str] = []
        for key, attempts in self._attempts.items():
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                stale.append(key)
        for key in stale:
            self._attempts.pop(key, None)
