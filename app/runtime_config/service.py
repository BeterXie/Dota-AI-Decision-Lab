from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.anthropic import AnthropicDecisionProvider
from app.ai.base import AiProvider, ai_experiment_key
from app.ai.chat_completions import KimiDecisionProvider
from app.ai.deepseek import DeepSeekDecisionProvider
from app.ai.gemini import GeminiDecisionProvider
from app.ai.openai import LocalOpenAiDecisionProvider, OpenAiDecisionProvider
from app.auth.social import SocialAuthSettings
from app.config import Settings, get_settings
from app.runtime_config.models import (
    AiProviderConfigRecord,
    RuntimeConfigAuditRecord,
    RuntimeSecretRecord,
    RuntimeSettingRecord,
)

AUTH_SETTING_KEYS = frozenset(
    {
        "auth.email.enabled",
        "auth.google.enabled",
        "auth.google.client_id",
        "auth.steam.enabled",
        "auth.external_base_url",
    }
)
AUTH_SECRET_KEY = "auth.google.client_secret"
AI_SECRET_KEYS = frozenset(
    {
        "ai.openai.api_key",
        "ai.local_openai.api_key",
        "ai.anthropic.api_key",
        "ai.gemini.api_key",
        "ai.deepseek.api_key",
        "ai.kimi.api_key",
    }
)
SUPPORTED_AI_PROVIDERS = frozenset(
    {"openai", "local_openai", "anthropic", "gemini", "deepseek", "kimi"}
)
_ALLOWED_REASONING_EFFORTS = frozenset({"low", "medium", "high"})
_ACTIVE_EXPERIMENT_CACHE: tuple[tuple[str, str, str, str, str], ...] | None = None


class RuntimeControlSettings(BaseSettings):
    """Bootstrap-only configuration needed to operate the DB control plane."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DOTA_RUNTIME_",
        extra="ignore",
    )

    config_master_key: SecretStr | None = None
    admin_emails: str = ""
    audit_limit: int = Field(default=200, ge=1, le=2_000)

    @property
    def admin_email_entries(self) -> tuple[str, ...]:
        return tuple(
            value.strip().lower() for value in self.admin_emails.split(",") if value.strip()
        )


@dataclass(frozen=True, slots=True)
class AuthRuntimeSnapshot:
    email_enabled: bool
    google_enabled: bool
    google_client_id: str | None
    google_client_secret: str | None
    steam_enabled: bool
    external_base_url: str | None

    @property
    def google_available(self) -> bool:
        return self.social_settings().google_available

    @property
    def steam_available(self) -> bool:
        return self.social_settings().steam_available

    @property
    def provider_payload(self) -> dict[str, bool]:
        return {
            "email": self.email_enabled,
            "google": self.google_available,
            "steam": self.steam_available,
        }

    def social_settings(self) -> SocialAuthSettings:
        return SocialAuthSettings(
            _env_file=None,
            external_base_url=self.external_base_url,
            google_enabled=self.google_enabled,
            google_client_id=self.google_client_id,
            google_client_secret=(
                SecretStr(self.google_client_secret) if self.google_client_secret else None
            ),
            steam_enabled=self.steam_enabled,
        )


@dataclass(frozen=True, slots=True)
class AiProviderRuntimeSnapshot:
    provider: str
    slot: str
    enabled: bool
    decisions_enabled: bool
    base_url: str
    model: str
    reasoning_effort: str | None
    timeout_seconds: float
    api_key_secret_key: str | None
    secret_configured: bool
    revision: int

    @property
    def experiment(self) -> tuple[str, str, str, str, str]:
        return ai_experiment_key(self.provider, self.model)


class RuntimeConfigurationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
        social_settings: SocialAuthSettings | None = None,
        bootstrap: RuntimeControlSettings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._social = social_settings or SocialAuthSettings()
        self.bootstrap = bootstrap or RuntimeControlSettings()

    async def auth_snapshot(self) -> AuthRuntimeSnapshot:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(RuntimeSettingRecord).where(
                            RuntimeSettingRecord.key.in_(AUTH_SETTING_KEYS)
                        )
                    )
                ).all()
            )
            values = self._auth_defaults()
            values.update({row.key: row.value for row in rows})
            google_secret = await self._read_secret(
                session,
                AUTH_SECRET_KEY,
                fallback=(
                    self._social.google_client_secret.get_secret_value()
                    if self._social.google_client_secret is not None
                    else None
                ),
            )
        return AuthRuntimeSnapshot(
            email_enabled=bool(values["auth.email.enabled"]),
            google_enabled=bool(values["auth.google.enabled"]),
            google_client_id=_optional_string(values["auth.google.client_id"]),
            google_client_secret=google_secret,
            steam_enabled=bool(values["auth.steam.enabled"]),
            external_base_url=_optional_string(values["auth.external_base_url"]),
        )

    async def ensure_seeded(self, *, actor: str | None = None) -> None:
        async with self._session_factory() as session, session.begin():
            await self._seed_settings(session, actor=actor)
            await self._seed_ai_providers(session, actor=actor)
            await self._seed_environment_secrets(session, actor=actor)
        _clear_active_experiment_cache()

    async def public_payload(self) -> dict[str, Any]:
        await self.ensure_seeded()
        async with self._session_factory() as session:
            settings = list(
                (
                    await session.scalars(
                        select(RuntimeSettingRecord).order_by(
                            RuntimeSettingRecord.category,
                            RuntimeSettingRecord.key,
                        )
                    )
                ).all()
            )
            providers = list(
                (
                    await session.scalars(
                        select(AiProviderConfigRecord).order_by(
                            AiProviderConfigRecord.provider,
                            AiProviderConfigRecord.slot,
                        )
                    )
                ).all()
            )
            secret_keys = set((await session.scalars(select(RuntimeSecretRecord.key))).all())
        secret_keys.update(self._environment_ai_secrets())
        if self._social.google_client_secret is not None:
            secret_keys.add(AUTH_SECRET_KEY)
        return {
            "settings": [self._setting_payload(row) for row in settings],
            "ai_providers": [
                self._provider_payload(row, secret_keys=secret_keys) for row in providers
            ],
            "bootstrap": {
                "encrypted_secret_storage_available": bool(self.bootstrap.config_master_key),
                "admin_email_count": len(self.bootstrap.admin_email_entries),
            },
        }

    async def set_setting(
        self,
        key: str,
        value: object,
        *,
        actor: str,
    ) -> dict[str, Any]:
        if key not in AUTH_SETTING_KEYS:
            raise ValueError(f"runtime setting is not mutable in v1: {key}")
        defaults = self._auth_defaults()
        normalized = _normalize_setting_value(key, value, defaults[key])
        async with self._session_factory() as session, session.begin():
            row = await session.get(RuntimeSettingRecord, key)
            previous = row.value if row is not None else defaults[key]
            if row is None:
                row = RuntimeSettingRecord(
                    key=key,
                    value=normalized,
                    value_type=_value_type(normalized),
                    category="auth",
                    description=_AUTH_DESCRIPTIONS[key],
                    revision=1,
                    updated_by=actor,
                    updated_at=datetime.now(UTC),
                )
                session.add(row)
            else:
                row.value = normalized
                row.value_type = _value_type(normalized)
                row.revision += 1
                row.updated_by = actor
                row.updated_at = datetime.now(UTC)
            session.add(
                RuntimeConfigAuditRecord(
                    target_key=key,
                    category="auth",
                    operation="UPDATE",
                    previous_value=previous,
                    new_value=normalized,
                    secret_changed=False,
                    actor=actor,
                    created_at=datetime.now(UTC),
                )
            )
            await session.flush()
            return self._setting_payload(row)

    async def upsert_ai_provider(
        self,
        provider: str,
        slot: str,
        payload: dict[str, object],
        *,
        actor: str,
    ) -> dict[str, Any]:
        if provider not in SUPPORTED_AI_PROVIDERS:
            raise ValueError(f"unsupported AI provider: {provider}")
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(AiProviderConfigRecord).where(
                    AiProviderConfigRecord.provider == provider,
                    AiProviderConfigRecord.slot == slot,
                )
            )
            if row is None:
                defaults = self._ai_defaults().get((provider, slot))
                if defaults is None:
                    raise ValueError(f"unknown AI provider slot: {provider}/{slot}")
                row = AiProviderConfigRecord(**defaults)
                session.add(row)
                await session.flush()
            previous = _provider_audit_value(row)
            _apply_provider_payload(row, payload)
            row.revision += 1
            row.updated_by = actor
            row.updated_at = datetime.now(UTC)
            session.add(
                RuntimeConfigAuditRecord(
                    target_key=f"ai_provider:{provider}:{slot}",
                    category="ai_provider",
                    operation="UPDATE",
                    previous_value=previous,
                    new_value=_provider_audit_value(row),
                    secret_changed=False,
                    actor=actor,
                    created_at=datetime.now(UTC),
                )
            )
            await session.flush()
            secret_keys = set((await session.scalars(select(RuntimeSecretRecord.key))).all())
            secret_keys.update(self._environment_ai_secrets())
            _clear_active_experiment_cache()
            return self._provider_payload(row, secret_keys=secret_keys)

    async def replace_secret(self, key: str, value: str, *, actor: str) -> dict[str, object]:
        if key not in self.allowed_secret_keys:
            raise ValueError("secret key is not managed by the runtime control plane")
        if not value:
            raise ValueError("secret value must not be empty")
        master = self._master_key()
        async with self._session_factory() as session, session.begin():
            if session.get_bind().dialect.name != "postgresql":
                raise RuntimeError("encrypted runtime secrets require PostgreSQL pgcrypto")
            existed = await session.get(RuntimeSecretRecord, key)
            now = datetime.now(UTC)
            await session.execute(
                text(
                    """
                    INSERT INTO runtime_secrets (key, ciphertext, revision, updated_by, updated_at)
                    VALUES (:key, pgp_sym_encrypt(:value, :master, 'cipher-algo=aes256'), 1, :actor, :now)
                    ON CONFLICT (key) DO UPDATE SET
                        ciphertext = pgp_sym_encrypt(:value, :master, 'cipher-algo=aes256'),
                        revision = runtime_secrets.revision + 1,
                        updated_by = :actor,
                        updated_at = :now
                    """
                ),
                {
                    "key": key,
                    "value": value,
                    "master": master,
                    "actor": actor,
                    "now": now,
                },
            )
            session.add(
                RuntimeConfigAuditRecord(
                    target_key=key,
                    category="secret",
                    operation="REPLACE" if existed is not None else "CREATE",
                    previous_value=None,
                    new_value=None,
                    secret_changed=True,
                    actor=actor,
                    created_at=now,
                )
            )
        return {"key": key, "configured": True}

    async def audit_payload(self, *, limit: int | None = None) -> list[dict[str, object]]:
        effective_limit = limit or self.bootstrap.audit_limit
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(RuntimeConfigAuditRecord)
                        .order_by(RuntimeConfigAuditRecord.created_at.desc())
                        .limit(effective_limit)
                    )
                ).all()
            )
        return [
            {
                "id": str(row.id),
                "target_key": row.target_key,
                "category": row.category,
                "operation": row.operation,
                "previous_value": row.previous_value,
                "new_value": row.new_value,
                "secret_changed": row.secret_changed,
                "actor": row.actor,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    @property
    def allowed_secret_keys(self) -> frozenset[str]:
        return frozenset({AUTH_SECRET_KEY, *AI_SECRET_KEYS})

    def is_admin_email(self, email: str | None) -> bool:
        return bool(email and email.strip().lower() in self.bootstrap.admin_email_entries)

    async def _seed_settings(self, session: AsyncSession, *, actor: str | None) -> None:
        existing = set((await session.scalars(select(RuntimeSettingRecord.key))).all())
        now = datetime.now(UTC)
        for key, value in self._auth_defaults().items():
            if key in existing:
                continue
            session.add(
                RuntimeSettingRecord(
                    key=key,
                    value=value,
                    value_type=_value_type(value),
                    category="auth",
                    description=_AUTH_DESCRIPTIONS[key],
                    revision=1,
                    updated_by=actor,
                    updated_at=now,
                )
            )

    async def _seed_ai_providers(self, session: AsyncSession, *, actor: str | None) -> None:
        existing = set(
            (
                await session.execute(
                    select(AiProviderConfigRecord.provider, AiProviderConfigRecord.slot)
                )
            ).all()
        )
        now = datetime.now(UTC)
        for key, values in self._ai_defaults().items():
            if key in existing:
                continue
            session.add(
                AiProviderConfigRecord(
                    **values,
                    revision=1,
                    updated_by=actor,
                    updated_at=now,
                )
            )

    async def _seed_environment_secrets(
        self,
        session: AsyncSession,
        *,
        actor: str | None,
    ) -> None:
        if self.bootstrap.config_master_key is None:
            return
        if session.get_bind().dialect.name != "postgresql":
            return
        existing = set((await session.scalars(select(RuntimeSecretRecord.key))).all())
        now = datetime.now(UTC)
        master = self._master_key()
        values = self._environment_ai_secrets()
        if self._social.google_client_secret is not None:
            values[AUTH_SECRET_KEY] = self._social.google_client_secret.get_secret_value()
        for key, value in values.items():
            if key in existing or not value:
                continue
            await session.execute(
                text(
                    """
                    INSERT INTO runtime_secrets (key, ciphertext, revision, updated_by, updated_at)
                    VALUES (:key, pgp_sym_encrypt(:value, :master, 'cipher-algo=aes256'), 1, :actor, :now)
                    """
                ),
                {
                    "key": key,
                    "value": value,
                    "master": master,
                    "actor": actor,
                    "now": now,
                },
            )

    async def _read_secret(
        self,
        session: AsyncSession,
        key: str,
        *,
        fallback: str | None = None,
    ) -> str | None:
        if self.bootstrap.config_master_key is None:
            return fallback
        if session.get_bind().dialect.name != "postgresql":
            return fallback
        result = await session.scalar(
            text(
                "SELECT pgp_sym_decrypt(ciphertext, :master) FROM runtime_secrets WHERE key = :key"
            ),
            {"master": self._master_key(), "key": key},
        )
        return str(result) if result is not None else fallback

    def _master_key(self) -> str:
        if self.bootstrap.config_master_key is None:
            raise RuntimeError("DOTA_RUNTIME_CONFIG_MASTER_KEY is required to manage DB secrets")
        value = self.bootstrap.config_master_key.get_secret_value()
        if len(value.encode("utf-8")) < 32:
            raise RuntimeError("DOTA_RUNTIME_CONFIG_MASTER_KEY must be at least 32 bytes")
        return value

    def _auth_defaults(self) -> dict[str, object]:
        return {
            "auth.email.enabled": bool(self._settings.auth_enabled),
            "auth.google.enabled": bool(self._social.google_enabled),
            "auth.google.client_id": self._social.google_client_id,
            "auth.steam.enabled": bool(self._social.steam_enabled),
            "auth.external_base_url": self._social.external_base_url,
        }

    def _ai_defaults(self) -> dict[tuple[str, str], dict[str, object]]:
        settings = self._settings
        return {
            ("openai", "default"): _provider_defaults(
                "openai",
                "default",
                enabled=settings.openai_api_key is not None,
                decisions_enabled=settings.openai_api_key is not None,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                reasoning_effort=settings.openai_reasoning_effort,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.openai.api_key",
            ),
            ("local_openai", "default"): _provider_defaults(
                "local_openai",
                "default",
                enabled=settings.local_openai_api_key is not None,
                decisions_enabled=settings.local_openai_api_key is not None,
                base_url=settings.local_openai_base_url,
                model=settings.local_openai_model,
                reasoning_effort=settings.local_openai_reasoning_effort,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.local_openai.api_key",
            ),
            ("anthropic", "default"): _provider_defaults(
                "anthropic",
                "default",
                enabled=settings.anthropic_api_key is not None,
                decisions_enabled=settings.anthropic_api_key is not None,
                base_url=settings.anthropic_base_url,
                model=settings.anthropic_model,
                reasoning_effort=None,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.anthropic.api_key",
            ),
            ("gemini", "default"): _provider_defaults(
                "gemini",
                "default",
                enabled=settings.gemini_api_key is not None,
                decisions_enabled=settings.gemini_api_key is not None,
                base_url=settings.gemini_base_url,
                model=settings.gemini_model,
                reasoning_effort=None,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.gemini.api_key",
            ),
            ("deepseek", "flash"): _provider_defaults(
                "deepseek",
                "flash",
                enabled=settings.deepseek_api_key is not None,
                decisions_enabled=settings.deepseek_flash_decisions_enabled,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                reasoning_effort=settings.deepseek_reasoning_effort,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.deepseek.api_key",
            ),
            ("deepseek", "pro"): _provider_defaults(
                "deepseek",
                "pro",
                enabled=settings.deepseek_api_key is not None,
                decisions_enabled=settings.deepseek_pro_decisions_enabled,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_pro_model,
                reasoning_effort=settings.deepseek_reasoning_effort,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.deepseek.api_key",
            ),
            ("kimi", "default"): _provider_defaults(
                "kimi",
                "default",
                enabled=settings.kimi_api_key is not None,
                decisions_enabled=settings.kimi_decisions_enabled,
                base_url=settings.kimi_base_url,
                model=settings.kimi_model,
                reasoning_effort=None,
                timeout_seconds=settings.ai_timeout_seconds,
                secret_key="ai.kimi.api_key",
            ),
        }

    def _environment_ai_secrets(self) -> dict[str, str]:
        settings = self._settings
        pairs = {
            "ai.openai.api_key": settings.openai_api_key,
            "ai.local_openai.api_key": settings.local_openai_api_key,
            "ai.anthropic.api_key": settings.anthropic_api_key,
            "ai.gemini.api_key": settings.gemini_api_key,
            "ai.deepseek.api_key": settings.deepseek_api_key,
            "ai.kimi.api_key": settings.kimi_api_key,
        }
        return {key: value.get_secret_value() for key, value in pairs.items() if value is not None}

    @staticmethod
    def _setting_payload(row: RuntimeSettingRecord) -> dict[str, object]:
        return {
            "key": row.key,
            "value": row.value,
            "value_type": row.value_type,
            "category": row.category,
            "description": row.description,
            "revision": row.revision,
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _provider_payload(
        row: AiProviderConfigRecord,
        *,
        secret_keys: set[str],
    ) -> dict[str, object]:
        return {
            "provider": row.provider,
            "slot": row.slot,
            "enabled": row.enabled,
            "decisions_enabled": row.decisions_enabled,
            "base_url": row.base_url,
            "model": row.model,
            "reasoning_effort": row.reasoning_effort,
            "reasoning_supported": row.provider in {"openai", "local_openai", "deepseek"},
            "timeout_seconds": row.timeout_seconds,
            "api_key_secret_key": row.api_key_secret_key,
            "secret_configured": bool(
                row.api_key_secret_key and row.api_key_secret_key in secret_keys
            ),
            "revision": row.revision,
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat(),
        }


async def active_ai_experiments(
    session: AsyncSession,
    fallback: tuple[tuple[str, str, str, str, str], ...] = (),
) -> tuple[tuple[str, str, str, str, str], ...]:
    rows = list(
        (
            await session.scalars(
                select(AiProviderConfigRecord)
                .where(
                    AiProviderConfigRecord.enabled.is_(True),
                    AiProviderConfigRecord.decisions_enabled.is_(True),
                )
                .order_by(AiProviderConfigRecord.provider, AiProviderConfigRecord.slot)
            )
        ).all()
    )
    any_row = await session.scalar(select(AiProviderConfigRecord.id).limit(1))
    experiments = (
        tuple(ai_experiment_key(row.provider, row.model) for row in rows)
        if any_row is not None
        else fallback
    )
    global _ACTIVE_EXPERIMENT_CACHE
    _ACTIVE_EXPERIMENT_CACHE = experiments
    return experiments


def cached_active_ai_experiments(
    fallback: tuple[tuple[str, str, str, str, str], ...],
) -> tuple[tuple[str, str, str, str, str], ...]:
    return _ACTIVE_EXPERIMENT_CACHE if _ACTIVE_EXPERIMENT_CACHE is not None else fallback


async def resolve_ai_provider(
    session: AsyncSession,
    provider: str,
    model: str,
    *,
    fallback: AiProvider | None,
) -> AiProvider:
    """Freeze the current provider row into a provider object for one call."""
    any_row = await session.scalar(select(AiProviderConfigRecord.id).limit(1))
    if any_row is None:
        if fallback is None:
            raise ValueError(f"AI provider experiment is not configured: {provider}/{model}")
        return fallback

    row = await session.scalar(
        select(AiProviderConfigRecord).where(
            AiProviderConfigRecord.provider == provider,
            AiProviderConfigRecord.model == model,
        )
    )
    if row is None or not row.enabled or not row.decisions_enabled:
        raise ValueError(f"AI provider experiment is disabled or superseded: {provider}/{model}")

    api_key = await _runtime_secret_or_environment(
        session,
        row.api_key_secret_key,
        bootstrap=RuntimeControlSettings(),
        settings=get_settings(),
    )
    if not api_key:
        raise ValueError(f"AI provider secret is not configured: {provider}/{row.slot}")
    resolved = _build_provider(row, api_key)
    setattr(resolved, "runtime_config_managed", True)
    setattr(resolved, "runtime_timeout_seconds", float(row.timeout_seconds))
    return resolved


def _build_provider(row: AiProviderConfigRecord, api_key: str) -> AiProvider:
    common = {
        "api_key": api_key,
        "model": row.model,
        "base_url": row.base_url,
        "timeout_seconds": row.timeout_seconds,
    }
    if row.provider == "openai":
        return OpenAiDecisionProvider(
            **common,
            reasoning_effort=row.reasoning_effort or "high",
        )
    if row.provider == "local_openai":
        return LocalOpenAiDecisionProvider(
            **common,
            reasoning_effort=row.reasoning_effort or "high",
        )
    if row.provider == "deepseek":
        return DeepSeekDecisionProvider(
            **common,
            reasoning_effort=row.reasoning_effort or "high",
        )
    if row.provider == "anthropic":
        return AnthropicDecisionProvider(**common)
    if row.provider == "gemini":
        return GeminiDecisionProvider(**common)
    if row.provider == "kimi":
        return KimiDecisionProvider(**common)
    raise ValueError(f"unsupported AI provider: {row.provider}")


async def _runtime_secret_or_environment(
    session: AsyncSession,
    secret_key: str | None,
    *,
    bootstrap: RuntimeControlSettings,
    settings: Settings,
) -> str | None:
    if secret_key and bootstrap.config_master_key is not None:
        if session.get_bind().dialect.name == "postgresql":
            master = bootstrap.config_master_key.get_secret_value()
            if len(master.encode("utf-8")) < 32:
                raise RuntimeError("DOTA_RUNTIME_CONFIG_MASTER_KEY must be at least 32 bytes")
            result = await session.scalar(
                text(
                    "SELECT pgp_sym_decrypt(ciphertext, :master) "
                    "FROM runtime_secrets WHERE key = :key"
                ),
                {"master": master, "key": secret_key},
            )
            if result is not None:
                return str(result)
    return _environment_secret(settings, secret_key)


def _environment_secret(settings: Settings, secret_key: str | None) -> str | None:
    values = {
        "ai.openai.api_key": settings.openai_api_key,
        "ai.local_openai.api_key": settings.local_openai_api_key,
        "ai.anthropic.api_key": settings.anthropic_api_key,
        "ai.gemini.api_key": settings.gemini_api_key,
        "ai.deepseek.api_key": settings.deepseek_api_key,
        "ai.kimi.api_key": settings.kimi_api_key,
    }
    value = values.get(secret_key or "")
    return value.get_secret_value() if value is not None else None


def _provider_defaults(
    provider: str,
    slot: str,
    *,
    enabled: bool,
    decisions_enabled: bool,
    base_url: str,
    model: str,
    reasoning_effort: str | None,
    timeout_seconds: float,
    secret_key: str,
) -> dict[str, object]:
    return {
        "provider": provider,
        "slot": slot,
        "enabled": enabled,
        "decisions_enabled": decisions_enabled,
        "base_url": base_url,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "timeout_seconds": timeout_seconds,
        "api_key_secret_key": secret_key,
    }


def _provider_audit_value(row: AiProviderConfigRecord) -> dict[str, object]:
    return {
        "provider": row.provider,
        "slot": row.slot,
        "enabled": row.enabled,
        "decisions_enabled": row.decisions_enabled,
        "base_url": row.base_url,
        "model": row.model,
        "reasoning_effort": row.reasoning_effort,
        "timeout_seconds": row.timeout_seconds,
        "api_key_secret_key": row.api_key_secret_key,
    }


def _apply_provider_payload(row: AiProviderConfigRecord, payload: dict[str, object]) -> None:
    allowed = {
        "enabled",
        "decisions_enabled",
        "base_url",
        "model",
        "reasoning_effort",
        "timeout_seconds",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported AI provider fields: {', '.join(sorted(unknown))}")
    if "enabled" in payload:
        row.enabled = _required_bool(payload["enabled"], "enabled")
    if "decisions_enabled" in payload:
        row.decisions_enabled = _required_bool(payload["decisions_enabled"], "decisions_enabled")
    if "base_url" in payload:
        row.base_url = _required_string(payload["base_url"], "base_url")
    if "model" in payload:
        row.model = _required_string(payload["model"], "model")
    if "reasoning_effort" in payload:
        value = payload["reasoning_effort"]
        if value is None:
            row.reasoning_effort = None
        else:
            effort = _required_string(value, "reasoning_effort").lower()
            if effort not in _ALLOWED_REASONING_EFFORTS:
                raise ValueError("reasoning_effort must be low, medium or high")
            row.reasoning_effort = effort
    if "timeout_seconds" in payload:
        value = payload["timeout_seconds"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("timeout_seconds must be numeric")
        timeout = float(value)
        if timeout <= 0 or timeout > 300:
            raise ValueError("timeout_seconds must be > 0 and <= 300")
        row.timeout_seconds = timeout


def _normalize_setting_value(key: str, value: object, default: object) -> object:
    if isinstance(default, bool):
        return _required_bool(value, key)
    if default is None or isinstance(default, str):
        if value is None:
            return None
        return _required_string(value, key)
    raise ValueError(f"unsupported runtime setting type: {key}")


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _value_type(value: object) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if value is None or isinstance(value, str):
        return "STRING"
    if isinstance(value, int | float):
        return "NUMBER"
    return "JSON"


def _clear_active_experiment_cache() -> None:
    global _ACTIVE_EXPERIMENT_CACHE
    _ACTIVE_EXPERIMENT_CACHE = None


_AUTH_DESCRIPTIONS = {
    "auth.email.enabled": "Allow passwordless email login requests.",
    "auth.google.enabled": "Allow Google OAuth login when credentials are configured.",
    "auth.google.client_id": "Google OAuth client id; client secret is stored separately.",
    "auth.steam.enabled": "Allow Steam OpenID login.",
    "auth.external_base_url": "Browser-visible origin used for social-login callbacks.",
}
