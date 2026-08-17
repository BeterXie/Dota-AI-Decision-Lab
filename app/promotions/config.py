from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PromotionSettings(BaseSettings):
    """Promotion/scoped-commerce switches isolated from core runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        validate_assignment=True,
    )

    referral_enabled: bool = False
    referral_campaign_key: str = "referral-v1"
    referral_claim_window_days: int = Field(default=7, ge=1, le=30)
    referral_inviter_reward_days: int = Field(default=7, ge=0, le=365)
    referral_invited_reward_days: int = Field(default=3, ge=0, le=365)
    referral_max_rewards_per_inviter: int = Field(default=20, ge=1, le=500)

    # One generic Paddle one-time price buys access to one canonical BO series.
    # The server binds the transaction to the selected series; the browser never
    # supplies an entitlement or duration directly.
    paddle_series_pass_price_id: str = ""
    paddle_series_pass_access_days: int = Field(default=3, ge=1, le=14)

    @property
    def series_pass_enabled(self) -> bool:
        return bool(self.paddle_series_pass_price_id.strip())
