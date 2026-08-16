from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, WebSocket, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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

    @app.middleware("http")
    async def require_authenticated_api(request: Request, call_next):
        if not enabled or _is_public_http_path(request.url.path):
            return await call_next(request)
        if request.url.path.startswith("/api/") or request.url.path == "/metrics":
            user = await _authenticate_cookie(service, request.cookies.get(SESSION_COOKIE_NAME))
            if user is None:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "authentication required"},
                )
            request.state.auth_user = user
        return await call_next(request)


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


async def authenticate_websocket(
    websocket: WebSocket,
    *,
    service: EmailAuthService | None,
    enabled: bool,
) -> AuthenticatedUser | None:
    if not enabled:
        return None
    user = await _authenticate_cookie(service, websocket.cookies.get(SESSION_COOKIE_NAME))
    if user is None:
        await websocket.close(code=4401, reason="authentication required")
        return None
    return user


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


def _user_payload(user: AuthenticatedUser) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "email_verified_at": user.email_verified_at,
        "created_at": user.created_at,
    }
