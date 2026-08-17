import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
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
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    EntitlementService,
)

_LOOPBACK_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
                            "premium access requires email authentication to be enabled"
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
        raise ValueError("auth is enabled but no email auth service was configured")
    app.include_router(
        _auth_router(
            service=service,
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
            active = await entitlements.ensure_development_grants(
                user.id,
                user.email,
                development_grant_emails,
            )
            grants = [item.public_payload() for item in await entitlements.active_grants(user.id)]
        return {
            "enabled": enabled,
            "authenticated": user is not None if enabled else True,
            "user": _user_payload(user) if user is not None else None,
            "entitlements": list(active),
            "grants": grants,
        }

    @router.get("/session")
    async def auth_session(request: Request) -> dict:
        if not enabled:
            return await session_payload(None)
        user = await _authenticate_cookie(service, request.cookies.get(SESSION_COOKIE_NAME))
        return await session_payload(user)

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
        max_age = max(1, int((result.expires_at - datetime.now(UTC)).total_seconds()))
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=result.token,
            max_age=max_age,
            path="/",
            secure=cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return await session_payload(result.user)

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
    service: EmailAuthService | None, token: str | None
) -> AuthenticatedUser | None:
    if service is None:
        return None
    return await service.authenticate(token)


def _require_service(service: EmailAuthService | None, enabled: bool) -> EmailAuthService:
    if not enabled or service is None:
        raise HTTPException(status_code=503, detail="email authentication is disabled")
    return service


def _http_access_requirement(path: str) -> tuple[str, str | None]:
    # Catalog discovery and provider callbacks do not carry a browser session.
    # The Paddle callback is authenticated cryptographically inside its route.
    if path == "/api/billing/offers" or path == "/api/billing/webhooks/paddle":
        return "PUBLIC", None
    if path == "/api/billing" or path.startswith("/api/billing/"):
        return "AUTHENTICATED", None
    # Notification Center and map-specific AI routes perform resource-aware
    # entitlement checks after identity is attached. Middleware only requires a
    # valid session so SERIES/MAP grants are not mistaken for GLOBAL Pro.
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
        path in {"/health", "/ready", "/api/runtime", "/api/matches"}
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
    # Non-browser clients do not necessarily send Origin; authentication still
    # applies to them, so absence is not an origin-policy bypass.
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
        "created_at": user.created_at,
    }
