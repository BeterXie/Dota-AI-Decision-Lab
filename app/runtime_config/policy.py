from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AI_VIEW_VERSION, DECISION_POLICY_VERSION, PROMPT_VERSION
from app.auth.social import SocialAuthSettings
from app.config import Settings, get_settings
from app.runtime_config.models import (
    RuntimeConfigAuditRecord,
    RuntimeSecretRecord,
    RuntimeSettingRecord,
)
from app.runtime_config.service import AUTH_SECRET_KEY, active_ai_experiments

AI_DECISION_SETTING_KEYS = frozenset(
    {
        "ai.decisions.enabled",
        "ai.max_live_data_lag_seconds",
        "ai.prior_decisions_limit",
    }
)
FEATURE_SETTING_KEYS = frozenset(
    {
        "feature.performance.enabled",
        "feature.billing_checkout.enabled",
    }
)
POLICY_SETTING_KEYS = frozenset({*AI_DECISION_SETTING_KEYS, *FEATURE_SETTING_KEYS})


@dataclass(frozen=True, slots=True)
class AiDecisionPolicySnapshot:
    enabled: bool
    max_live_data_lag_seconds: float
    prior_decisions_limit: int


class RuntimePolicyService:
    """Runtime-safe policy settings that can change without rebuilding workers.

    This service intentionally excludes process-lifecycle switches such as QQ,
    WeChat, RayBet and DLTV worker construction. Those remain visible to the
    control plane as lifecycle-managed capabilities until the supervisor can
    add/remove long-running workers dynamically.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
        social_settings: SocialAuthSettings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._social = social_settings or SocialAuthSettings()

    async def ensure_seeded(self, *, actor: str | None = None) -> None:
        defaults = self._defaults()
        async with self._session_factory() as session, session.begin():
            existing = set((await session.scalars(select(RuntimeSettingRecord.key))).all())
            now = datetime.now(UTC)
            for key, value in defaults.items():
                if key in existing:
                    continue
                session.add(
                    RuntimeSettingRecord(
                        key=key,
                        value=value,
                        value_type=_value_type(value),
                        category=_category_for(key),
                        description=_DESCRIPTIONS[key],
                        revision=1,
                        updated_by=actor,
                        updated_at=now,
                    )
                )

    async def public_payload(self) -> dict[str, Any]:
        await self.ensure_seeded()
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(RuntimeSettingRecord)
                        .where(RuntimeSettingRecord.key.in_(POLICY_SETTING_KEYS))
                        .order_by(RuntimeSettingRecord.category, RuntimeSettingRecord.key)
                    )
                ).all()
            )
        return {
            "settings": [_setting_payload(row) for row in rows],
            "ai_contract": {
                "prompt_version": PROMPT_VERSION,
                "decision_policy_version": DECISION_POLICY_VERSION,
                "ai_view_version": AI_VIEW_VERSION,
                "fan_out_strategy": "PARALLEL_ACTIVE_PROVIDERS",
                "worker_concurrency": int(self._settings.ai_worker_concurrency),
                "worker_concurrency_hot_mutable": False,
            },
            "lifecycle_features": self._lifecycle_features(),
        }

    async def set_setting(self, key: str, value: object, *, actor: str) -> dict[str, Any]:
        defaults = self._defaults()
        if key not in defaults:
            raise ValueError(f"runtime policy setting is not mutable: {key}")
        normalized = _normalize_policy_value(key, value)
        async with self._session_factory() as session, session.begin():
            row = await session.get(RuntimeSettingRecord, key)
            previous = row.value if row is not None else defaults[key]
            now = datetime.now(UTC)
            if row is None:
                row = RuntimeSettingRecord(
                    key=key,
                    value=normalized,
                    value_type=_value_type(normalized),
                    category=_category_for(key),
                    description=_DESCRIPTIONS[key],
                    revision=1,
                    updated_by=actor,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.value = normalized
                row.value_type = _value_type(normalized)
                row.revision += 1
                row.updated_by = actor
                row.updated_at = now
            session.add(
                RuntimeConfigAuditRecord(
                    target_key=key,
                    category=_category_for(key),
                    operation="UPDATE",
                    previous_value=previous,
                    new_value=normalized,
                    secret_changed=False,
                    actor=actor,
                    created_at=now,
                )
            )
            await session.flush()
            return _setting_payload(row)

    async def feature_enabled(self, key: str) -> bool:
        if key not in FEATURE_SETTING_KEYS and key != "ai.decisions.enabled":
            raise ValueError(f"unknown runtime feature flag: {key}")
        async with self._session_factory() as session:
            row = await session.get(RuntimeSettingRecord, key)
        if row is not None:
            return bool(row.value)
        return bool(self._defaults()[key])

    async def secret_status_payload(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            db_keys = set((await session.scalars(select(RuntimeSecretRecord.key))).all())
        bootstrap_keys = self._bootstrap_secret_keys()
        items = []
        for key, label, category in _SECRET_CATALOG:
            if key in db_keys:
                storage = "DATABASE_ENCRYPTED"
            elif key in bootstrap_keys:
                storage = "BOOTSTRAP_FALLBACK"
            else:
                storage = "NOT_CONFIGURED"
            items.append(
                {
                    "key": key,
                    "label": label,
                    "category": category,
                    "configured": storage != "NOT_CONFIGURED",
                    "storage": storage,
                    "runtime_hot": True,
                }
            )
        return {"items": items}

    def _defaults(self) -> dict[str, object]:
        return {
            "ai.decisions.enabled": True,
            "ai.max_live_data_lag_seconds": float(self._settings.ai_max_live_data_lag_seconds),
            "ai.prior_decisions_limit": int(self._settings.ai_prior_decisions_limit),
            "feature.performance.enabled": True,
            "feature.billing_checkout.enabled": True,
        }

    def _bootstrap_secret_keys(self) -> set[str]:
        settings = self._settings
        keys = {
            key
            for key, value in {
                "ai.openai.api_key": settings.openai_api_key,
                "ai.local_openai.api_key": settings.local_openai_api_key,
                "ai.anthropic.api_key": settings.anthropic_api_key,
                "ai.gemini.api_key": settings.gemini_api_key,
                "ai.deepseek.api_key": settings.deepseek_api_key,
                "ai.kimi.api_key": settings.kimi_api_key,
            }.items()
            if value is not None
        }
        if self._social.google_client_secret is not None:
            keys.add(AUTH_SECRET_KEY)
        return keys

    def _lifecycle_features(self) -> list[dict[str, object]]:
        settings = self._settings
        return [
            _lifecycle(
                "email_notifications", "Email notifications", settings.email_notifications_enabled
            ),
            _lifecycle("qq_bot", "QQ Bot", settings.qq_bot_enabled),
            _lifecycle("wechat_clawbot", "WeChat ClawBot", settings.wechat_clawbot_enabled),
            _lifecycle("raybet_workers", "RayBet collectors", settings.run_provider_workers),
            _lifecycle("dltv_workers", "DLTV collectors", settings.run_provider_workers),
        ]


async def ai_decision_policy_snapshot(
    session: AsyncSession,
    *,
    fallback_max_live_data_lag_seconds: float = 120.0,
    fallback_prior_decisions_limit: int = 10,
) -> AiDecisionPolicySnapshot:
    rows = list(
        (
            await session.scalars(
                select(RuntimeSettingRecord).where(
                    RuntimeSettingRecord.key.in_(AI_DECISION_SETTING_KEYS)
                )
            )
        ).all()
    )
    values = {row.key: row.value for row in rows}
    return AiDecisionPolicySnapshot(
        enabled=bool(values.get("ai.decisions.enabled", True)),
        max_live_data_lag_seconds=float(
            values.get("ai.max_live_data_lag_seconds", fallback_max_live_data_lag_seconds)
        ),
        prior_decisions_limit=int(
            values.get("ai.prior_decisions_limit", fallback_prior_decisions_limit)
        ),
    )


async def active_runtime_ai_experiments(
    session: AsyncSession,
    fallback: tuple[tuple[str, str, str, str, str], ...] = (),
) -> tuple[tuple[str, str, str, str, str], ...]:
    policy = await ai_decision_policy_snapshot(session)
    if not policy.enabled:
        return ()
    return await active_ai_experiments(session, fallback)


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


def _normalize_policy_value(key: str, value: object) -> object:
    if key in {
        "ai.decisions.enabled",
        "feature.performance.enabled",
        "feature.billing_checkout.enabled",
    }:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be boolean")
        return value
    if key == "ai.max_live_data_lag_seconds":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("ai.max_live_data_lag_seconds must be numeric")
        normalized = float(value)
        if normalized <= 0 or normalized > 3_600:
            raise ValueError("ai.max_live_data_lag_seconds must be > 0 and <= 3600")
        return normalized
    if key == "ai.prior_decisions_limit":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("ai.prior_decisions_limit must be an integer")
        if value < 1 or value > 100:
            raise ValueError("ai.prior_decisions_limit must be between 1 and 100")
        return value
    raise ValueError(f"unsupported runtime policy setting: {key}")


def _value_type(value: object) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int | float):
        return "NUMBER"
    if isinstance(value, str):
        return "STRING"
    return "JSON"


def _category_for(key: str) -> str:
    return "ai_decision" if key in AI_DECISION_SETTING_KEYS else "feature"


def _lifecycle(key: str, label: str, enabled: bool) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "enabled": bool(enabled),
        "hot_mutable": False,
        "reason": "Needs Dynamic Supervisor before no-restart worker toggling is safe.",
    }


_DESCRIPTIONS = {
    "ai.decisions.enabled": "Schedule new AI jobs; prepared inference continues.",
    "ai.max_live_data_lag_seconds": "Maximum delayed live-data lag included in new AI inputs.",
    "ai.prior_decisions_limit": (
        "Maximum recent prior decisions included in each new AI provider input."
    ),
    "feature.performance.enabled": "Allow AI Performance and review quality API access.",
    "feature.billing_checkout.enabled": (
        "Allow new billing checkout creation while keeping account and webhook maintenance active."
    ),
}

_SECRET_CATALOG = (
    (AUTH_SECRET_KEY, "Google Client Secret", "authentication"),
    ("ai.openai.api_key", "OpenAI API Key", "ai"),
    ("ai.local_openai.api_key", "Local OpenAI-compatible API Key", "ai"),
    ("ai.anthropic.api_key", "Anthropic API Key", "ai"),
    ("ai.gemini.api_key", "Gemini API Key", "ai"),
    ("ai.deepseek.api_key", "DeepSeek API Key", "ai"),
    ("ai.kimi.api_key", "Kimi API Key", "ai"),
)
