from app.promotions.config import PromotionSettings


def test_promotions_are_disabled_by_default() -> None:
    settings = PromotionSettings(_env_file=None)
    assert settings.referral_enabled is False
