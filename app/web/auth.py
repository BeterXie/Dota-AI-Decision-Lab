from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth import (
    SESSION_COOKIE_NAME,
    AuthDeliveryError,
    AuthenticatedUser,
    EmailAuthService,
    InvalidEmailError,
    InvalidLoginCodeError,
)


class RequestLoginCodePayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyLoginCodePayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=1, max_length=20)


class AuthGuardMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        service: EmailAuthService | None,
        enabled: bool,
    ) -> None:
        self._app = app
        self._service = service
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._enabled:
            await self._app(scope, receive, send)
            return
        scope_type = scope["type"]
        path = scope.get("path", "")
        if scope_type == "http":
            if _is_public_http_path(path) or not _is_protected_http_path(path):
                await self._app(scope, receive, send)
                return
            user = await self._authenticated_scope_user(scope)
            if user is None:
                await JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "authentication required"},
                )(scope, receive, send)
                return
            scope.setdefault("state", {})["auth_user"] = user
        elif scope_type == "websocket":
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
    enabled: bool,
    cookie_secure: bool,
) -> None:
    if enabled and service is None:
        raise ValueError("auth is enabled but no email auth service was configured")
    app.include_router(_auth_router(service=service, enabled=enabled, cookie_secure=cookie_secure))
    app.add_middleware(AuthGuardMiddleware, service=service, enabled=enabled)


def _auth_router(
    *,
    service: EmailAuthService | None,
    enabled: bool,
    cookie_secure: bool,
) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.get("/session")
    async def auth_session(request: Request) -> dict:
        if not enabled:
            return {"enabled": False, "authenticated": True, "user": None}
        user = await _authenticate_cookie(service, request.cookies.get(SESSION_COOKIE_NAME))
        return {
            "enabled": True,
            "authenticated": user is not None,
            "user": _user_payload(user) if user is not None else None,
        }

    @router.post("/request-code", status_code=status.HTTP_202_ACCEPTED)
    async def request_code(payload: RequestLoginCodePayload) -> dict:
        auth = _require_service(service, enabled)
        try:
            result = await auth.request_login_code(payload.email)
        except InvalidEmailError as exc:
            raise HTTPException(status_code=422, detail="invalid email address") from exc
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
        return {
            "enabled": True,
            "authenticated": True,
            "user": _user_payload(result.user),
        }

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


def _is_public_http_path(path: str) -> bool:
    return path in {"/health", "/ready"} or path.startswith("/api/auth/")


def _is_protected_http_path(path: str) -> bool:
    return path.startswith("/api/") or path == "/metrics"


def _user_payload(user: AuthenticatedUser) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "email_verified_at": user.email_verified_at,
        "created_at": user.created_at,
    }
