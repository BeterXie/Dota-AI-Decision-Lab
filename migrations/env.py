import asyncio
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app import models  # noqa: F401
from app.auth import models as auth_models  # noqa: F401
from app.billing import models as billing_models  # noqa: F401
from app.config import get_settings
from app.db import Base
from app.entitlements import models as entitlement_models  # noqa: F401
from app.evaluation import portfolio_models as portfolio_models  # noqa: F401
from app.identity import roster_models as roster_models  # noqa: F401
from app.notifications import models as notification_models  # noqa: F401
from app.promotions import models as promotion_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata

_MANAGED_PARTITION = re.compile(
    r"^(provider_raw_events|odds_observations|dltv_live_observations|decision_future_odds)"
    r"_(default|\d{8})$"
)


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    if type_ == "table":
        return name is None or _MANAGED_PARTITION.fullmatch(name) is None
    if type_ == "index":
        table_name = parent_names.get("table_name")
        return table_name is None or _MANAGED_PARTITION.fullmatch(table_name) is None
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
