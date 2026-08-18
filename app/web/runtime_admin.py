from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.runtime_config import RuntimeConfigurationService


class RuntimeSettingUpdate(BaseModel):
    value: Any


class AiProviderUpdate(BaseModel):
    enabled: bool | None = None
    decisions_enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)

    def changes(self) -> dict[str, object]:
        return self.model_dump(exclude_unset=True)


class RuntimeSecretUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)


def create_runtime_admin_router(service: RuntimeConfigurationService) -> APIRouter:
    router = APIRouter(prefix="/api/admin/runtime", tags=["runtime-admin"])

    @router.get("/config")
    async def runtime_config(request: Request) -> dict[str, Any]:
        _admin_actor(request, service)
        return await service.public_payload()

    @router.patch("/settings/{key:path}")
    async def update_setting(
        key: str,
        payload: RuntimeSettingUpdate,
        request: Request,
    ) -> dict[str, object]:
        actor = _admin_actor(request, service)
        try:
            return await service.set_setting(key, payload.value, actor=actor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.patch("/ai-providers/{provider}/{slot}")
    async def update_ai_provider(
        provider: str,
        slot: str,
        payload: AiProviderUpdate,
        request: Request,
    ) -> dict[str, Any]:
        actor = _admin_actor(request, service)
        changes = payload.changes()
        if not changes:
            raise HTTPException(status_code=422, detail="at least one provider field is required")
        try:
            return await service.upsert_ai_provider(provider, slot, changes, actor=actor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/secrets/{key:path}")
    async def replace_secret(
        key: str,
        payload: RuntimeSecretUpdate,
        request: Request,
    ) -> dict[str, object]:
        actor = _admin_actor(request, service)
        try:
            return await service.replace_secret(key, payload.value, actor=actor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @router.get("/audit")
    async def runtime_audit(request: Request, limit: int = 200) -> dict[str, object]:
        _admin_actor(request, service)
        if limit < 1 or limit > 2_000:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 2000")
        return {"items": await service.audit_payload(limit=limit)}

    return router


def _admin_actor(request: Request, service: RuntimeConfigurationService) -> str:
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    email = getattr(user, "email", None)
    if not service.is_admin_email(email):
        raise HTTPException(status_code=403, detail="runtime configuration admin access required")
    return str(email).strip().lower()
