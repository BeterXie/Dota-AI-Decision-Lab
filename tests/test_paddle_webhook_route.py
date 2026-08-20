import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.billing.paddle import PaddleApiClient, PaddleCatalogPrice
from app.config import Settings
from app.db import Base
from app.web.billing import create_billing_router


@pytest.mark.asyncio
async def test_billing_offers_include_active_catalog_prices(monkeypatch) -> None:
    requested_prices: list[str] = []

    async def get_price(_client: PaddleApiClient, price_id: str) -> PaddleCatalogPrice:
        requested_prices.append(price_id)
        amount = "499" if price_id == "pri_test_series" else "4999"
        return PaddleCatalogPrice(
            price_id=price_id,
            amount=amount,
            currency_code="CNY",
            status="active",
            recurring=False,
        )

    monkeypatch.setattr(PaddleApiClient, "get_price", get_price)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(
        create_billing_router(
            factory,
            Settings(
                _env_file=None,
                auth_enabled=True,
                paddle_enabled=True,
                paddle_api_key="pdl_sdbx_apikey_test",
                paddle_webhook_secret="pdl_ntfset_test",
                paddle_series_pass_price_id="pri_test_series",
                paddle_event_pass_price_id="pri_test_event",
            ),
        )
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/billing/offers")
            cached_response = await client.get("/api/billing/offers")
        assert response.status_code == 200
        assert cached_response.status_code == 200
        assert requested_prices == ["pri_test_series", "pri_test_event"]
        payload = response.json()
        assert payload["series_pass"]["price"] == {
            "id": "pri_test_series",
            "amount": "499",
            "currency_code": "CNY",
        }
        assert payload["event_pass"]["price"] == {
            "id": "pri_test_event",
            "amount": "4999",
            "currency_code": "CNY",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_paddle_webhook_rejects_oversized_body_before_signature_processing() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(
        create_billing_router(
            factory,
            Settings(
                _env_file=None,
                auth_enabled=True,
                paddle_enabled=True,
                paddle_api_key="pdl_sdbx_apikey_test",
                paddle_webhook_secret="pdl_ntfset_test",
                paddle_series_pass_price_id="pri_test_series",
                paddle_event_pass_price_id="pri_test_event",
            ),
        )
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/billing/webhooks/paddle",
                content=b"x" * (1_048_576 + 1),
            )
        assert response.status_code == 413
        assert response.json() == {"detail": "Paddle webhook body is too large"}
    finally:
        await engine.dispose()
