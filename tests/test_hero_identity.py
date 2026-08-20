import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.identity.resolver import IdentityResolver
from app.models import CanonicalHero


@pytest.mark.asyncio
async def test_dltv_hero_identity_seeds_and_repairs_display_name() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    resolver = IdentityResolver()

    async with factory.begin() as session:
        await resolver.resolve_dltv_hero(session, 35)

    async with factory.begin() as session:
        hero = await session.get(CanonicalHero, 35)
        assert hero is not None and hero.name == "Sniper"
        hero.name = None
        await resolver.resolve_dltv_hero(session, 35, name="Sniper")

    async with factory() as session:
        hero = await session.get(CanonicalHero, 35)
        assert hero is not None and hero.name == "Sniper"
    await engine.dispose()
