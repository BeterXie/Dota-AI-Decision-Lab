from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser
from app.promotions import PromotionDisabledError, PromotionService, ReferralClaimError


class ReferralClaimPayload(BaseModel):
    code: str = Field(min_length=3, max_length=32)


def create_promotion_router(service: PromotionService) -> APIRouter:
    router = APIRouter(prefix="/api/promotions", tags=["promotions"])

    @router.get("/referral")
    async def referral_overview(request: Request) -> dict:
        user = _request_user(request)
        return await service.overview(user.id)

    @router.post("/referral/claim")
    async def claim_referral(payload: ReferralClaimPayload, request: Request) -> dict:
        user = _request_user(request)
        try:
            attribution = await service.claim_referral(user.id, payload.code)
        except PromotionDisabledError as exc:
            raise HTTPException(status_code=404, detail="referral campaign is disabled") from exc
        except ReferralClaimError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "claimed": True,
            "campaign_key": attribution.campaign_key,
            "status": attribution.status,
            "claimed_at": attribution.claimed_at,
        }

    return router


def _request_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, AuthenticatedUser):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user
