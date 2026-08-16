from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.runtime.health import HealthRegistry
from app.web import create_app
from app.web.spa import spa_file_response


def test_spa_file_response_never_escapes_frontend_dist(tmp_path: Path) -> None:
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("INDEX", encoding="utf-8")
    secret = tmp_path / "secret.env"
    secret.write_text("TOP_SECRET", encoding="utf-8")

    response = spa_file_response(dist, "../../secret.env")
    assert Path(response.path).resolve() == (dist / "index.html").resolve()


@pytest.mark.asyncio
async def test_spa_encoded_traversal_falls_back_to_index(tmp_path: Path) -> None:
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("INDEX", encoding="utf-8")
    (tmp_path / "secret.env").write_text("TOP_SECRET", encoding="utf-8")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app = create_app(
        async_sessionmaker(engine, expire_on_commit=False), HealthRegistry(), frontend_dist=dist
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/..%2F..%2Fsecret.env", "/%2e%2e/%2e%2e/secret.env", "/..%5C..%5Csecret.env"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.text == "INDEX"
            assert "TOP_SECRET" not in response.text
    await engine.dispose()
