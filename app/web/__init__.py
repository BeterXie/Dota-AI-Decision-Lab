from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import EmailAuthService, ResendLoginCodeSender
from app.config import Settings, get_settings
from app.entitlements import EntitlementService
from app.runtime.health import HealthRegistry
from app.web.api import create_app as create_api_app
from app.web.auth import register_auth
from app.web.billing import create_billing_router
from app.web.notifications import create_notification_router
from app.web.player_hero_recent import register_player_hero_recent_routes
from app.web.premium import create_premium_router
from app.web.public_boundary import PublicMatchDataBoundaryMiddleware
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
    auth_enabled: bool | None = None,
    auth_cookie_secure: bool | None = None,
    development_grant_emails: tuple[str, ...] = (),
    settings: Settings | None = None,
) -> FastAPI:
    runtime_settings = settings
    owns_auth_service = False
    if auth_enabled is None:
        runtime_settings = runtime_settings or get_settings()
        auth_enabled = runtime_settings.auth_enabled
    if auth_cookie_secure is None:
        runtime_settings = runtime_settings or get_settings()
        auth_cookie_secure = runtime_settings.auth_cookie_secure
    if auth_enabled and auth_service is None:
        runtime_settings = runtime_settings or get_settings()
        auth_service = _configured_auth_service(runtime_settings, session_factory)
        owns_auth_service = True

    # Main passes the already validated runtime settings explicitly. Tests and
    # focused app fixtures fall back to the normal settings loader.
    runtime_settings = runtime_settings or get_settings()
    entitlement_service = EntitlementService(session_factory)

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
    app.include_router(
        create_premium_router(
            session_factory,
            live_state_max_age_seconds=live_state_max_age_seconds,
            live_market_max_age_seconds=live_market_max_age_seconds,
            market_max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
    )
    app.include_router(create_notification_router(session_factory))
    app.include_router(create_billing_router(session_factory, runtime_settings))
    register_auth(
        app,
        service=auth_service,
        entitlements=entitlement_service,
        enabled=auth_enabled,
        cookie_secure=auth_cookie_secure,
        development_grant_emails=development_grant_emails,
    )
    # This is deliberately independent of frontend behavior: even a hand-written
    # HTTP client cannot extract premium decision payloads from public match APIs.
    app.add_middleware(PublicMatchDataBoundaryMiddleware)
    if owns_auth_service and auth_service is not None:
        app.router.add_event_handler("shutdown", auth_service.close)

    if frontend_dist is not None and frontend_dist.is_dir():
        assets = frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def frontend(full_path: str) -> FileResponse:
            return spa_file_response(frontend_dist, full_path)

    return app


def _configured_auth_service(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> EmailAuthService:
    if settings.auth_configuration_errors:
        missing = ", ".join(settings.auth_configuration_errors)
        raise RuntimeError(f"email authentication configuration is incomplete: {missing}")
    if (
        settings.auth_secret_key is None
        or settings.resend_api_key is None
        or not settings.resend_from
    ):
        raise RuntimeError("validated email authentication configuration is incomplete")
    sender = ResendLoginCodeSender(
        api_key=settings.resend_api_key.get_secret_value(),
        sender_from=settings.resend_from,
        base_url=settings.resend_base_url,
        timeout_seconds=settings.resend_timeout_seconds,
        subject_prefix=settings.auth_email_subject_prefix,
    )
    return EmailAuthService(
        session_factory=session_factory,
        sender=sender,
        secret_key=settings.auth_secret_key.get_secret_value(),
        login_code_ttl_seconds=settings.auth_login_code_ttl_seconds,
        resend_cooldown_seconds=settings.auth_login_resend_cooldown_seconds,
        max_attempts=settings.auth_login_max_attempts,
        session_ttl_days=settings.auth_session_ttl_days,
    )


__all__ = ["WebServerWorker", "create_app"]
