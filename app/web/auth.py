import json
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth import (
    SESSION_COOKIE_NAME,
    AuthDeliveryError,
    AuthenticatedUser,
    AuthRateLimitError,
    EmailAuthService,
    InvalidEmailError,
    InvalidLoginCodeError,
)
from app.auth.social import SocialAuthProviderError, SocialAuthService, SocialAuthSettings
from app.entitlements import AI_DECISIONS_ENTITLEMENT, EntitlementService

_LOOPBACK_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SOCIAL_STATE_COOKIE = "dota_auth_state"
_SOCIAL_RETURN_COOKIE = "dota_auth_return_to"
_SOCIAL_STATE_MAX_AGE = 600


class RequestLoginCodePayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyLoginCodePayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=1, max_length=20)


class AuthGuardMiddleware:
    """Attach identity and enforce an explicit, fail-closed API access policy."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        service: EmailAuthService | None,
        entitlements: EntitlementService,
        enabled: bool,
    ) -> None:
        self._app = app
        self._service = service
        self._entitlements = entitlements
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        path = scope.get("path", "")
        if scope_type == "http":
            access, required_entitlement = _http_access_requirement(path)
            if not self._enabled:
                if access != "PUBLIC":
                    await _json_error(
                        send,
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=(
                            "premium access requires authentication to be enabled"
                            if access == "ENTITLED"
                            else "authentication is disabled for this protected endpoint"
                        ),
                        required_entitlement=required_entitlement,
                    )
                    return
                await self._app(scope, receive, send)
                return
            user = await self._authenticated_scope_user(scope)
            active_entitlements: tuple[str, ...] = ()
            if user is not None:
                active_entitlements = await self._entitlements.active_entitlements(user.id)
                state = scope.setdefault("state", {})
                state["auth_user"] = user
                state["auth_entitlements"] = active_entitlements
            if access in {"AUTHENTICATED", "ENTITLED"} and user is None:
                await _json_error(
                    send,
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="authentication required",
                    required_entitlement=required_entitlement,
                )
                return
            if (
                access == "ENTITLED"
                and required_entitlement is not None
                and required_entitlement not in active_entitlements
            ):
                await _json_error(
                    send,
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="entitlement required",
                    required_entitlement=required_entitlement,
                )
                return
        elif scope_type == "websocket":
            if not _websocket_origin_allowed(_scope_origin(scope)):
                await send(
                    {
                        "type": "websocket.close",
                        "code": 4403,
                        "reason": "websocket origin is not allowed",
                    }
                )
                return
            if not self._enabled:
                await send(
                    {
                        "type": "websocket.close",
                        "code": 4403,
                        "reason": "authentication is disabled",
                    }
                )
                return
            user = await self._authenticated_scope_user(scope)
            if user is None:
                await send(
                    {
                        "type": "websocket.close",
                        "code": 4401,
                        "reason": "authentication required",
                    }
                )
                return
            scope.setdefault("state", {})["auth_user"] = user
        await self._app(scope, receive, send)

    async def _authenticated_scope_user(self, scope: Scope) -> AuthenticatedUser | None:
        connection = HTTPConnection(scope)
        return await _authenticate_cookie(
            self._service,
            connection.cookies.get(SESSION_COOKIE_NAME),
        )


def register_auth(
    app: FastAPI,
    *,
    service: EmailAuthService | None,
    entitlements: EntitlementService,
    enabled: bool,
    cookie_secure: bool,
    development_grant_emails: tuple[str, ...] = (),
) -> None:
    if enabled and service is None:
        raise ValueError("auth is enabled but no auth service was configured")
    social = SocialAuthService(SocialAuthSettings())
    app.include_router(
        _auth_router(
            service=service,
            social=social,
            entitlements=entitlements,
            enabled=enabled,
            cookie_secure=cookie_secure,
            development_grant_emails=development_grant_emails,
        )
    )
    app.add_middleware(
        AuthGuardMiddleware,
        service=service,
        entitlements=entitlements,
        enabled=enabled,
    )


def _auth_router(
    *,
    service: EmailAuthService | None,
    social: SocialAuthService,
    entitlements: EntitlementService,
    enabled: bool,
    cookie_secure: bool,
    development_grant_emails: tuple[str, ...],
) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    async def session_payload(user: AuthenticatedUser | None) -> dict:
        active: tuple[str, ...] = ()
        grants: list[dict] = []
        if user is not None:
            if user.email is not None:
                active = await entitlements.ensure_development_grants(
                    user.id,
                    user.email,
                    development_grant_emails,
                )
            else:
                active = await entitlements.active_entitlements(user.id)
            grants = [item.public_payload() for item in await entitlements.active_grants(user.id)]
        return {
            "enabled": enabled,
            "authenticated": user is not None if enabled else True,
            "user": _user_payload(user) if user is not None else None,
            "entitlements": list(active),
            "grants": grants,
            "providers": {
                "email": enabled,
                "google": enabled and social.settings.google_available,
                "steam": enabled and social.settings.steam_available,
            },
        }

    @router.get("/session")
    async def auth_session(request: Request) -> dict:
        if not enabled:
            return await session_payload(None)
        user = await _authenticate_cookie(service, request.cookies.get(SESSION_COOKIE_NAME))
        return await session_payload(user)

    @router.get("/providers")
    async def auth_providers() -> dict:
        return {
            "enabled": enabled,
            "providers": {
                "email": enabled,
                "google": enabled and social.settings.google_available,
                "steam": enabled and social.settings.steam_available,
            },
        }

    @router.post("/request-code", status_code=status.HTTP_202_ACCEPTED)
    async def request_code(payload: RequestLoginCodePayload, request: Request) -> dict:
        auth = _require_service(service, enabled)
        request_source = request.client.host if request.client is not None else None
        try:
            result = await auth.request_login_code(
                payload.email,
                request_source=request_source,
            )
        except InvalidEmailError as exc:
            raise HTTPException(status_code=422, detail="invalid email address") from exc
        except AuthRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many login code requests",
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except AuthDeliveryError as exc:
            raise HTTPException(status_code=503, detail="login email delivery failed") from exc
        return {
            "accepted": True,
            "sent": result.sent,
            "retry_after_seconds": result.retry_after_seconds,
        }

    @router.post("/verify-code")
    async def verify_code(payload: VerifyLoginCodePayload, response: Response) -> dict:
        auth = _require_service(service, enabled)
        try:
            result = await auth.verify_login_code(payload.email, payload.code)
        except InvalidEmailError as exc:
            raise HTTPException(status_code=422, detail="invalid email address") from exc
        except InvalidLoginCodeError as exc:
            raise HTTPException(status_code=401, detail="invalid or expired login code") from exc
        _set_session_cookie(response, result.token, result.expires_at, cookie_secure)
        return await session_payload(result.user)

    @router.get("/google/start")
    async def google_start(return_to: str = "/") -> Response:
        _require_service(service, enabled)
        state_value = secrets.token_urlsafe(32)
        try:
            target = social.google_authorization_url(state_value)
        except SocialAuthProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
        _set_social_state(response, "google", state_value, return_to, cookie_secure)
        return response

    @router.get("/google/callback")
    async def google_callback(request: Request) -> Response:
        auth = _require_service(service, enabled)
        state_value = request.query_params.get("state")
        _validate_social_state(request, "google", state_value)
        return_to = _return_to_from_cookie(request)
        if request.query_params.get("error") or not request.query_params.get("code"):
            return _social_failure_redirect(return_to, "google_cancelled", cookie_secure)
        try:
            claim = await social.google_identity(request.query_params["code"])
            result = await auth.login_external_identity(
                provider=claim.provider,
                subject=claim.subject,
                email=claim.email,
                email_verified=claim.email_verified,
                display_name=claim.display_name,
                avatar_url=claim.avatar_url,
            )
        except Exception:
            return _social_failure_redirect(return_to, "google_failed", cookie_secure)
        response = RedirectResponse(return_to, status_code=status.HTTP_302_FOUND)
        _set_session_cookie(response, result.token, result.expires_at, cookie_secure)
        _clear_social_state(response, cookie_secure)
        return response

    @router.get("/steam/start")
    async def steam_start(return_to: str = "/") -> Response:
        _require_service(service, enabled)
        state_value = secrets.token_urlsafe(32)
        try:
            target = social.steam_authorization_url(state_value)
        except SocialAuthProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
        _set_social_state(response, "steam", state_value, return_to, cookie_secure)
        return response

    @router.get("/steam/callback")
    async def steam_callback(request: Request) -> Response:
        auth = _require_service(service, enabled)
        state_value = request.query_params.get("state")
        expected_state = _validate_social_state(request, "steam", state_value)
        return_to = _return_to_from_cookie(request)
        try:
            params = {key: value for key, value in request.query_params.items()}
            claim = await social.steam_identity(params, expected_state)
            result = await auth.login_external_identity(
                provider=claim.provider,
                subject=claim.subject,
                display_name=claim.display_name,
            )
        except Exception:
            return _social_failure_redirect(return_to, "steam_failed", cookie_secure)
        response = RedirectResponse(return_to, status_code=status.HTTP_302_FOUND)
        _set_session_cookie(response, result.token, result.expires_at, cookie_secure)
        _clear_social_state(response, cookie_secure)
        return response

    @router.post("/logout")
    async def logout(request: Request, response: Response) -> dict:
        if service is not None:
            await service.logout(request.cookies.get(SESSION_COOKIE_NAME))
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            secure=cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return {"ok": True}

    return router


async def _authenticate_cookie(
    service: EmailAuthService | None,
    token: str | None,
) -> AuthenticatedUser | None:
    if service is None:
        return None
    return await service.authenticate(token)


def _require_service(service: EmailAuthService | None, enabled: bool) -> EmailAuthService:
    if not enabled or service is None:
        raise HTTPException(status_code=503, detail="authentication is disabled")
    return service


def _set_session_cookie(
    response: Response,
    token: str,
    expires_at: datetime,
    cookie_secure: bool,
) -> None:
    max_age = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        secure=cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _set_social_state(
    response: Response,
    provider: str,
    state_value: str,
    return_to: str,
    cookie_secure: bool,
) -> None:
    response.set_cookie(
        _SOCIAL_STATE_COOKIE,
        f"{provider}:{state_value}",
        max_age=_SOCIAL_STATE_MAX_AGE,
        path="/api/auth/",
        secure=cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        _SOCIAL_RETURN_COOKIE,
        _safe_return_to(return_to),
        max_age=_SOCIAL_STATE_MAX_AGE,
        path="/api/auth/",
        secure=cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _validate_social_state(
    request: Request,
    provider: str,
    supplied: str | None,
) -> str:
    stored = request.cookies.get(_SOCIAL_STATE_COOKIE)
    if not supplied or not stored or stored != f"{provider}:{supplied}":
        raise HTTPException(status_code=400, detail="invalid authentication state")
    return supplied


def _return_to_from_cookie(request: Request) -> str:
    return _safe_return_to(request.cookies.get(_SOCIAL_RETURN_COOKIE) or "/")


def _clear_social_state(response: Response, cookie_secure: bool) -> None:
    for key in (_SOCIAL_STATE_COOKIE, _SOCIAL_RETURN_COOKIE):
        response.delete_cookie(
            key,
            path="/api/auth/",
            secure=cookie_secure,
            httponly=True,
            samesite="lax",
        )


def _social_failure_redirect(return_to: str, code: str, cookie_secure: bool) -> Response:
    separator = "&" if "?" in return_to else "?"
    response = RedirectResponse(
        f"{return_to}{separator}{urlencode({'auth_error': code})}",
        status_code=status.HTTP_302_FOUND,
    )
    _clear_social_state(response, cookie_secure)
    return response


def _safe_return_to(value: str) -> str:
    cleaned = value.strip()
    if (
        not cleaned.startswith("/")
        or cleaned.startswith("//")
        or "\\" in cleaned
        or len(cleaned) > 500
    ):
        return "/"
    return cleaned


def _http_access_requirement(path: str) -> tuple[str, str | None]:
    if path == "/api/billing/offers" or path == "/api/billing/webhooks/paddle":
        return "PUBLIC", None
    if path == "/api/billing" or path.startswith("/api/billing/"):
        return "AUTHENTICATED", None
    if path == "/api/notifications" or path.startswith("/api/notifications/"):
        return "AUTHENTICATED", None
    if path.startswith("/api/maps/") and path.endswith("/ai-decisions"):
        return "AUTHENTICATED", None
    if (
        path == "/api/snapshots"
        or path.startswith("/api/snapshots/")
        or path == "/api/review"
        or path.startswith("/api/review/")
    ):
        return "ENTITLED", AI_DECISIONS_ENTITLEMENT
    if path == "/metrics" or path == "/api/jobs/summary" or path.startswith("/api/account/"):
        return "AUTHENTICATED", None
    if (
        path in {"/health", "/ready", "/api/runtime", "/api/matches", "/api/teams"}
        or path.startswith("/api/teams/")
        or path == "/api/auth"
        or path.startswith("/api/auth/")
        or _is_public_map_path(path)
    ):
        return "PUBLIC", None
    if path.startswith("/api/"):
        return "AUTHENTICATED", None
    return "PUBLIC", None


def _is_public_map_path(path: str) -> bool:
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) == 3 and segments[:2] == ["api", "maps"]:
        return True
    return (
        len(segments) == 4
        and segments[:2] == ["api", "maps"]
        and segments[3] == "draft-hero-recent"
    )


def _scope_origin(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"origin":
            return value.decode("latin-1")
    return None


def _websocket_origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in _LOOPBACK_ORIGIN_HOSTS


async def _json_error(
    send: Send,
    *,
    status_code: int,
    detail: str,
    required_entitlement: str | None,
) -> None:
    payload: dict[str, str] = {"detail": detail}
    if required_entitlement is not None:
        payload["required_entitlement"] = required_entitlement
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _user_payload(user: AuthenticatedUser) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "email_verified_at": user.email_verified_at,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at,
    }
