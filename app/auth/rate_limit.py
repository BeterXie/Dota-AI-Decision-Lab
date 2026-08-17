import asyncio
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class LoginRequestLimiter:
    """Single-runtime sliding-window limiter for passwordless login delivery.

    Remote serving is not enabled yet, so the current trust boundary is one
    loopback runtime. The limiter deliberately uses only the direct peer source
    supplied by the ASGI server; proxy-forwarded headers are not trusted.

    The internal lock protects only small in-memory deque mutations. It is never
    held while database or email-provider I/O is running.
    """

    def __init__(
        self,
        *,
        source_max_requests: int,
        source_window_seconds: int,
        global_max_requests: int,
        global_window_seconds: int,
    ) -> None:
        if source_max_requests < 1 or global_max_requests < 1:
            raise ValueError("login rate-limit request counts must be positive")
        if source_window_seconds < 1 or global_window_seconds < 1:
            raise ValueError("login rate-limit windows must be positive")
        self._source_max_requests = source_max_requests
        self._source_window_seconds = source_window_seconds
        self._global_max_requests = global_max_requests
        self._global_window_seconds = global_window_seconds
        self._global_attempts: deque[float] = deque()
        self._source_attempts: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, source: str | None) -> RateLimitDecision:
        now = time.monotonic()
        normalized_source = source.strip() if source and source.strip() else None
        async with self._lock:
            self._prune(self._global_attempts, now - self._global_window_seconds)
            self._prune_sources(now)
            global_retry = self._retry_after(
                self._global_attempts,
                now=now,
                max_requests=self._global_max_requests,
                window_seconds=self._global_window_seconds,
            )
            if global_retry:
                return RateLimitDecision(False, global_retry)

            source_attempts: deque[float] | None = None
            if normalized_source is not None:
                source_attempts = self._source_attempts.setdefault(normalized_source, deque())
                source_retry = self._retry_after(
                    source_attempts,
                    now=now,
                    max_requests=self._source_max_requests,
                    window_seconds=self._source_window_seconds,
                )
                if source_retry:
                    return RateLimitDecision(False, source_retry)

            self._global_attempts.append(now)
            if source_attempts is not None:
                source_attempts.append(now)
            return RateLimitDecision(True)

    @staticmethod
    def _prune(attempts: deque[float], cutoff: float) -> None:
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

    def _prune_sources(self, now: float) -> None:
        cutoff = now - self._source_window_seconds
        empty: list[str] = []
        for source, attempts in self._source_attempts.items():
            self._prune(attempts, cutoff)
            if not attempts:
                empty.append(source)
        for source in empty:
            self._source_attempts.pop(source, None)

    @staticmethod
    def _retry_after(
        attempts: deque[float],
        *,
        now: float,
        max_requests: int,
        window_seconds: int,
    ) -> int:
        if len(attempts) < max_requests:
            return 0
        remaining = window_seconds - (now - attempts[0])
        return max(1, int(remaining + 0.999))
