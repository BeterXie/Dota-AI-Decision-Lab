from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.runtime_config.policy import RuntimePolicyService


class RuntimeFeatureFlagMiddleware(BaseHTTPMiddleware):
    """Hard backend gates for runtime-safe feature flags.

    Billing webhooks/account maintenance deliberately stay reachable when new
    checkout creation is disabled, so subscription state can still reconcile.
    """

    def __init__(self, app, *, policy: RuntimePolicyService) -> None:
        super().__init__(app)
        self._policy = policy

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/api/review/"):
            if not await self._policy.feature_enabled("feature.performance.enabled"):
                return _disabled("AI Performance is disabled by runtime configuration")
        if request.method == "POST" and _is_new_checkout_path(path):
            if not await self._policy.feature_enabled("feature.billing_checkout.enabled"):
                return _disabled("new billing checkout is disabled by runtime configuration")
        return await call_next(request)


def _is_new_checkout_path(path: str) -> bool:
    if not path.startswith("/api/billing/"):
        return False
    return path.startswith("/api/billing/checkout/") or (
        path.startswith("/api/billing/series/") and path.endswith("/checkout")
    )


def _disabled(detail: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": detail})
