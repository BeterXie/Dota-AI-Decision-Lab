from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.runtime_config import RuntimeConfigurationService, RuntimePolicyService
from app.runtime_config.provider_safety import validate_provider_base_url


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


def create_runtime_admin_router(
    service: RuntimeConfigurationService,
    policy: RuntimePolicyService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/runtime", tags=["runtime-admin"])

    @router.get("/config")
    async def runtime_config(request: Request) -> dict[str, Any]:
        _admin_actor(request, service)
        return await service.public_payload()

    @router.get("/policy")
    async def runtime_policy(request: Request) -> dict[str, Any]:
        _admin_actor(request, service)
        return await _require_policy(policy).public_payload()

    @router.get("/secrets")
    async def runtime_secrets(request: Request) -> dict[str, Any]:
        _admin_actor(request, service)
        return await _require_policy(policy).secret_status_payload()

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

    @router.patch("/policy/{key:path}")
    async def update_policy_setting(
        key: str,
        payload: RuntimeSettingUpdate,
        request: Request,
    ) -> dict[str, object]:
        actor = _admin_actor(request, service)
        try:
            return await _require_policy(policy).set_setting(key, payload.value, actor=actor)
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
            guarded = await _validated_provider_changes(
                service,
                _require_policy(policy),
                provider,
                slot,
                changes,
            )
            return await service.upsert_ai_provider(provider, slot, guarded, actor=actor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="AI provider identity conflicts with another configured slot",
            ) from exc

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


async def _validated_provider_changes(
    service: RuntimeConfigurationService,
    policy: RuntimePolicyService,
    provider: str,
    slot: str,
    changes: dict[str, object],
) -> dict[str, object]:
    config = await service.public_payload()
    providers = list(config.get("ai_providers", []))
    current = next(
        (
            item
            for item in providers
            if item.get("provider") == provider and item.get("slot") == slot
        ),
        None,
    )
    if current is None:
        raise ValueError(f"unknown AI provider slot: {provider}/{slot}")

    prospective_model = str(changes.get("model", current.get("model", ""))).strip()
    if not prospective_model:
        raise ValueError("model must be a non-empty string")
    for item in providers:
        if item is current:
            continue
        if (
            item.get("provider") == provider
            and item.get("slot") != slot
            and str(item.get("model", "")).strip() == prospective_model
        ):
            raise ValueError(
                f"provider/model identity already belongs to another slot: "
                f"{provider}/{prospective_model}"
            )

    prospective_base_url = str(changes.get("base_url", current.get("base_url", "")))
    normalized_base_url = validate_provider_base_url(provider, prospective_base_url)
    if "base_url" in changes:
        changes = {**changes, "base_url": normalized_base_url}

    prospective_enabled = bool(changes.get("enabled", current.get("enabled", False)))
    prospective_decisions = bool(
        changes.get("decisions_enabled", current.get("decisions_enabled", False))
    )
    if prospective_decisions and not prospective_enabled:
        raise ValueError("decisions_enabled requires the provider to be enabled")
    if prospective_decisions:
        secret_key = current.get("api_key_secret_key")
        statuses = await policy.secret_status_payload()
        secret = next(
            (item for item in statuses.get("items", []) if item.get("key") == secret_key),
            None,
        )
        if secret is None or not bool(secret.get("operational")):
            raise ValueError(f"AI provider credential is not operational: {provider}/{slot}")
    return changes


def _admin_actor(request: Request, service: RuntimeConfigurationService) -> str:
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    email = getattr(user, "email", None)
    if not service.is_admin_email(email):
        raise HTTPException(status_code=403, detail="runtime configuration admin access required")
    return str(email).strip().lower()


def _require_policy(policy: RuntimePolicyService | None) -> RuntimePolicyService:
    if policy is None:
        raise HTTPException(status_code=503, detail="runtime policy service is unavailable")
    return policy
