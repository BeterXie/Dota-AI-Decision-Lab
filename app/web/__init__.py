from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import EmailAuthService, ResendLoginCodeSender
from app.auth.development import (
    LocalDevelopmentAuth,
    LocalLoginCodeSender,
    local_development_auth_from_environment,
)
from app.config import Settings, get_settings
from app.entitlements import EntitlementService
from app.promotions import PromotionService
from app.promotions.config import PromotionSettings
from app.runtime.health import HealthRegistry
from app.runtime_config import RuntimeConfigurationService, RuntimePolicyService
from app.web.access import create_access_router
from app.web.api import create_app as create_api_app
from app.web.auth import register_auth
from app.web.billing import create_billing_router
from app.web.feature_flags import RuntimeFeatureFlagMiddleware
from app.web.notifications import UserQrBindingService, create_notification_router
from app.web.player_hero_recent import register_player_hero_recent_routes
from app.web.premium import create_premium_router
from app.web.promotions import create_promotion_router
from app.web.public_boundary import PublicMatchDataBoundaryMiddleware
from app.web.quality import create_quality_router
from app.web.runtime_admin import create_runtime_admin_router
from app.web.server import WebServerWorker
from app.web.spa import spa_file_response
from app.web.teams import create_team_router

logger = structlog.get_logger()
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
    promotion_settings: PromotionSettings | None = None,
    qq_pairing_link_factory: Callable[[str], Awaitable[str]] | None = None,
    qq_contact_url: str | None = None,
    wechat_contact_url: str | None = None,
    qq_qr_binding_service: UserQrBindingService | None = None,
    wechat_qr_binding_service: UserQrBindingService | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    if auth_enabled is None:
        auth_enabled = runtime_settings.auth_enabled
    if auth_cookie_secure is None:
        auth_cookie_secure = runtime_settings.auth_cookie_secure

    local_auth = local_development_auth_from_environment()
    if local_auth.enabled:
        _assert_local_development_auth_safety(
            runtime_settings,
            auth_enabled=auth_enabled,
            auth_cookie_secure=auth_cookie_secure,
        )
        if not development_grant_emails:
            development_grant_emails = (local_auth.pro_email,)
        logger.warning(
            "local_development_auth_enabled",
            pro_email=local_auth.pro_email,
            code_path=str(local_auth.code_path),
        )

    owns_auth_service = False
    if auth_enabled and auth_service is None:
        auth_service = _configured_auth_service(
            runtime_settings,
            session_factory,
            local_auth=local_auth,
        )
        owns_auth_service = True

    promotions = promotion_settings or PromotionSettings()
    entitlement_service = EntitlementService(session_factory)
    control_plane_settings = runtime_settings.model_copy(
        update={"auth_enabled": bool(auth_enabled)}
    )
    runtime_config = RuntimeConfigurationService(
        session_factory,
        settings=control_plane_settings,
    )
    runtime_policy = RuntimePolicyService(
        session_factory,
        settings=control_plane_settings,
    )
    promotion_service = PromotionService(
        session_factory,
        referral_enabled=promotions.referral_enabled,
        campaign_key=promotions.referral_campaign_key,
        claim_window_days=promotions.referral_claim_window_days,
        inviter_reward_days=promotions.referral_inviter_reward_days,
        invited_reward_days=promotions.referral_invited_reward_days,
        max_rewards_per_inviter=promotions.referral_max_rewards_per_inviter,
    )

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
    app.include_router(create_team_router(session_factory))
    app.include_router(
        create_premium_router(
            session_factory,
            live_state_max_age_seconds=live_state_max_age_seconds,
            live_market_max_age_seconds=live_market_max_age_seconds,
            market_max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
    )
    app.include_router(create_access_router(session_factory, entitlement_service))
    app.include_router(
        create_notification_router(
            session_factory,
            qq_pairing_link_factory=qq_pairing_link_factory,
            qq_contact_url=qq_contact_url,
            wechat_contact_url=wechat_contact_url,
            qq_qr_binding_service=qq_qr_binding_service,
            wechat_qr_binding_service=wechat_qr_binding_service,
        )
    )
    app.include_router(create_promotion_router(promotion_service))
    app.include_router(create_quality_router(session_factory))
    app.include_router(create_runtime_admin_router(runtime_config, runtime_policy))
    app.include_router(
        create_billing_router(
            session_factory,
            runtime_settings,
            promotion_settings=promotions,
            promotion_service=promotion_service,
        )
    )
    register_auth(
        app,
        service=auth_service,
        entitlements=entitlement_service,
        enabled=auth_enabled,
        cookie_secure=auth_cookie_secure,
        development_grant_emails=development_grant_emails,
        runtime_config=runtime_config,
    )
    app.router.add_event_handler("startup", runtime_config.ensure_seeded)
    app.router.add_event_handler("startup", runtime_policy.ensure_seeded)
    app.add_middleware(RuntimeFeatureFlagMiddleware, policy=runtime_policy)
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
    *,
    local_auth: LocalDevelopmentAuth,
) -> EmailAuthService:
    if local_auth.enabled:
        secret_key = _validated_auth_secret(settings)
        sender = LocalLoginCodeSender(local_auth.code_path)
    else:
        if settings.auth_configuration_errors:
            missing = ", ".join(settings.auth_configuration_errors)
            raise RuntimeError(f"email authentication configuration is incomplete: {missing}")
        if (
            settings.auth_secret_key is None
            or settings.resend_api_key is None
            or not settings.resend_from
        ):
            raise RuntimeError("validated email authentication configuration is incomplete")
        secret_key = settings.auth_secret_key.get_secret_value()
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
        secret_key=secret_key,
        login_code_ttl_seconds=settings.auth_login_code_ttl_seconds,
        resend_cooldown_seconds=settings.auth_login_resend_cooldown_seconds,
        max_attempts=settings.auth_login_max_attempts,
        session_ttl_days=settings.auth_session_ttl_days,
    )


def _validated_auth_secret(settings: Settings) -> str:
    if settings.auth_secret_key is None:
        raise RuntimeError("email authentication configuration is incomplete: AUTH_SECRET_KEY")
    secret_key = settings.auth_secret_key.get_secret_value()
    if len(secret_key.encode("utf-8")) < 32:
        raise RuntimeError(
            "email authentication configuration is incomplete: AUTH_SECRET_KEY>=32_BYTES"
        )
    return secret_key


def _assert_local_development_auth_safety(
    settings: Settings,
    *,
    auth_enabled: bool,
    auth_cookie_secure: bool,
) -> None:
    if not auth_enabled:
        raise RuntimeError("local development auth requires AUTH_ENABLED=true")
    if settings.host not in _LOOPBACK_HOSTS:
        raise RuntimeError("local development auth is restricted to loopback hosts")
    if auth_cookie_secure:
        raise RuntimeError(
            "local development auth requires AUTH_COOKIE_SECURE=false for loopback HTTP"
        )


__all__ = ["WebServerWorker", "create_app"]
