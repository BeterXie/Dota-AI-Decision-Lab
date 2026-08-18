from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.liquipedia.discovery import LiquipediaDiscoveryService
from app.providers.liquipedia.fetch import (
    LIQUIPEDIA_PARSE_INTERVAL_SECONDS,
    LiquipediaMediaWikiClient,
)
from app.providers.liquipedia.projection import LiquipediaCanonicalProjector, ProjectionResult
from app.repositories.raw import RawEventRepository

LIQUIPEDIA_SCHEDULE_REFRESH_SECONDS = 900.0
LIQUIPEDIA_TOURNAMENT_REFRESH_SECONDS = 21_600.0
LIQUIPEDIA_FAILURE_RETRY_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class LiquipediaSeedResult:
    source: str | None
    observations: int = 0
    projection: ProjectionResult | None = None


class LiquipediaRuntimeSeeder:
    """Refresh one due Liquipedia page before a RayBet discovery pass.

    Only one ``action=parse`` request is issued per invocation. Schedule data is
    preferred because it directly seeds canonical series for later odds linking.
    The tournament directory is refreshed on the next eligible invocation when
    both sources are due.
    """

    def __init__(
        self,
        raw_events: RawEventRepository,
        *,
        client: LiquipediaMediaWikiClient | None = None,
        schedule_refresh_seconds: float = LIQUIPEDIA_SCHEDULE_REFRESH_SECONDS,
        tournament_refresh_seconds: float = LIQUIPEDIA_TOURNAMENT_REFRESH_SECONDS,
        failure_retry_seconds: float = LIQUIPEDIA_FAILURE_RETRY_SECONDS,
    ) -> None:
        if schedule_refresh_seconds <= 0 or tournament_refresh_seconds <= 0:
            raise ValueError("Liquipedia refresh intervals must be positive")
        if failure_retry_seconds <= 0:
            raise ValueError("Liquipedia failure retry interval must be positive")
        self._client = client or LiquipediaMediaWikiClient()
        self._discovery = LiquipediaDiscoveryService(self._client, raw_events)
        self._projector = LiquipediaCanonicalProjector()
        self._schedule_refresh_seconds = schedule_refresh_seconds
        self._tournament_refresh_seconds = tournament_refresh_seconds
        self._failure_retry_seconds = failure_retry_seconds
        self._last_schedule_at: float | None = None
        self._last_tournament_at: float | None = None
        self._last_parse_attempt_at: float | None = None
        self._retry_not_before = 0.0

    async def refresh_one_due(self, session: AsyncSession) -> LiquipediaSeedResult:
        now = monotonic()
        if now < self._retry_not_before:
            return LiquipediaSeedResult(source=None)
        if (
            self._last_parse_attempt_at is not None
            and now - self._last_parse_attempt_at < LIQUIPEDIA_PARSE_INTERVAL_SECONDS
        ):
            return LiquipediaSeedResult(source=None)

        source = self._next_due_source(now)
        if source is None:
            return LiquipediaSeedResult(source=None)
        self._last_parse_attempt_at = now
        try:
            if source == "schedule":
                observations = await self._discovery.discover_global_schedule(session)
                if not observations:
                    raise ValueError("Liquipedia global schedule produced no observations")
                projection = await self._projector.project_series(session, observations)
                self._last_schedule_at = monotonic()
            else:
                observations = await self._discovery.discover_tournaments(session)
                if not observations:
                    raise ValueError("Liquipedia tournament directory produced no observations")
                projection = await self._projector.project_tournaments(session, observations)
                self._last_tournament_at = monotonic()
        except Exception:
            self._retry_not_before = monotonic() + self._failure_retry_seconds
            raise
        self._retry_not_before = 0.0
        return LiquipediaSeedResult(
            source=source,
            observations=len(observations),
            projection=projection,
        )

    async def close(self) -> None:
        await self._client.close()

    def _next_due_source(self, now: float) -> str | None:
        if (
            self._last_schedule_at is None
            or now - self._last_schedule_at >= self._schedule_refresh_seconds
        ):
            return "schedule"
        if (
            self._last_tournament_at is None
            or now - self._last_tournament_at >= self._tournament_refresh_seconds
        ):
            return "tournaments"
        return None
