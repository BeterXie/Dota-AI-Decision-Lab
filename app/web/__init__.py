from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import EmailAuthService
from app.runtime.health import HealthRegistry
from app.web.api import create_app as create_api_app
from app.web.auth import register_auth
from app.web.player_hero_recent import register_player_hero_recent_routes
from app.web.server import WebServerWorker
from app.web.spa import spa_file_response


def create_app(
    session_factory: async_sessionmaker[AsyncSession],
    health: HealthRegistry,
    *,
    frontend_dist: Path | None = None,
    live_state_max_age_seconds: float = 45.0,
    live_market_max_age_seconds: float = 30.0,
    market_max_pair_skew_seconds: float = 5.0,
    ai_min_game_time_seconds: int = 600,
    auth_service: EmailAuthService | None = None,
    auth_enabled: bool = False,
    auth_cookie_secure: bool = False,
) -> FastAPI:
    # Build API routes first without the SPA catch-all, so detail-scoped
    # extension routes remain reachable before the frontend fallback route.
    app = create_api_app(
        session_factory,
        health,
        frontend_dist=None,
        live_state_max_age_seconds=live_state_max_age_seconds,
        live_market_max_age_seconds=live_market_max_age_seconds,
        market_max_pair_skew_seconds=market_max_pair_skew_seconds,
        ai_min_game_time_seconds=ai_min_game_time_seconds,
    )
    register_player_hero_recent_routes(app, session_factory)
    register_auth(
        app,
        service=auth_service,
        enabled=auth_enabled,
        cookie_secure=auth_cookie_secure,
    )

    if frontend_dist is not None and frontend_dist.is_dir():
        assets = frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def frontend(full_path: str) -> FileResponse:
            return spa_file_response(frontend_dist, full_path)

    return app


__all__ = ["WebServerWorker", "create_app"]
