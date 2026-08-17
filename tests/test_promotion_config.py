from app.promotions.config import PromotionSettings


def test_promotions_are_disabled_by_default() -> None:
    settings = PromotionSettings(_env_file=None)
    assert settings.referral_enabled is False
    assert settings.series_pass_enabled is False
    assert settings.paddle_series_pass_access_days == 3
