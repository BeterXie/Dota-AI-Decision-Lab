from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RAYBET_INFO_BASE_URLS = (
    "https://cfinfo.365raylinks.com/v2",
    "https://iminfo.esportsworldlink.com/v2",
    "https://cfinfo.365raylines.com/v2",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/dota_ai_decision_lab"

    # Empty default so the legacy singular spelling below actually works as a
    # fallback for existing .env files; the built-in hosts apply only when
    # neither variable is configured.
    raybet_info_base_urls: str = ""
    # Legacy singular spelling kept for backward compatibility with existing
    # .env files; used only when the plural list is empty.
    raybet_info_base_url: str | None = None
    raybet_socket_url: str = "wss://cfsocket.365raylinks.com/socketcluster/"
    raybet_origin: str = "https://www.ray086.com"
    raybet_dota_game_id: int = 151
    raybet_naive_timezone: str = "Asia/Shanghai"
    raybet_match_types: str = "0,1,2"
    raybet_discovery_interval_seconds: float = 30.0

    dltv_base_url: str = "https://dltv.org"
    dltv_bootstrap_interval_seconds: float = 30.0

    stratz_graphql_url: str = "https://api.stratz.com/graphql"
    stratz_token: SecretStr | None = None
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_api_key: SecretStr | None = None
    historical_refresh_seconds: float = 1_200.0
    historical_prewarm_maps: int = 100
    historical_sync_batch_maps: int = 20

    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.6-terra"
    openai_reasoning_effort: str = "xhigh"
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_model: str = "claude-sonnet-4-6"
    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.6-flash"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_pro_model: str = "deepseek-v4-pro"
    deepseek_reasoning_effort: str = "high"
    kimi_api_key: SecretStr | None = None
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2.5"
    ai_timeout_seconds: float = 240.0
    # Delayed DLTV broadcast data beyond this lag is excluded from the AI input
    # (the decision then uses only freeze-time consistent information).
    ai_max_live_data_lag_seconds: float = 120.0
    # The deepseek flash model still powers email translation; this flag only
    # controls whether it also produces decision votes (off by default).
    deepseek_flash_decisions_enabled: bool = False

    email_notifications_enabled: bool = False
    email_recipients: str = ""
    email_subject_prefix: str = "[Dota AI Decision Lab]"
    resend_api_key: SecretStr | None = None
    resend_from: str | None = None
    resend_base_url: str = "https://api.resend.com"
    resend_timeout_seconds: float = Field(default=30.0, gt=0)

    # Calibrated against production RayBet/DLTV signal cadence: DLTV state
    # changes arrive event-driven every ~40-60s with a median pairing lag of
    # ~10-23s, so the original 3s/8s thresholds could never be satisfied.
    live_sync_safe_seconds: float = 30.0
    live_sync_caution_seconds: float = 60.0
    live_sync_calibration_window_seconds: float = 30.0
    live_sync_min_samples: int = 3
    live_sync_nw_signal_threshold: int = 500
    live_sync_ambiguity_margin_seconds: float = 0.5
    live_sync_min_accepted_pair_ratio: float = 0.6
    live_market_max_age_seconds: float = 30.0
    market_max_pair_skew_seconds: float = 5.0
    # DLTV fast-state updates every ~40-60s (event driven, not per second), so
    # a 45s freshness window would falsely age out live fields between updates.
    live_state_max_age_seconds: float = 120.0
    historical_max_age_seconds: float = 7_200.0
    delayed_detail_max_delay_seconds: float = 30.0

    elo_initial_rating: float = 1_500.0
    elo_k_factor: float = 24.0
    ai_min_game_time_seconds: int = Field(default=600, ge=0)
    ai_checkpoint_minutes: str = "10,15,20,25,30,35,40,45,50,55,60"
    significant_odds_move: float = 0.05
    decision_cooldown_seconds: float = 60.0
    future_odds_horizons_seconds: str = "30,60,180,300"

    run_provider_workers: bool = True
    auto_migrate: bool = True
    provider_business_message_max_age_seconds: float = 120.0
    worker_heartbeat_seconds: float = 10.0
    worker_max_backoff_seconds: float = 60.0
    job_poll_seconds: float = 1.0
    job_lease_seconds: float = 120.0
    reconciliation_interval_seconds: float = 60.0
    metrics_enabled: bool = True
    otel_exporter_otlp_endpoint: str | None = None
    host: str = "127.0.0.1"
    # Set when binding a non-loopback host; the runtime refuses to start on a
    # non-loopback address without it. CORS is not an auth boundary.
    api_token: SecretStr | None = None
    port: int = Field(default=8000, ge=1, le=65_535)
    log_level: str = "INFO"

    @property
    def checkpoint_minutes(self) -> tuple[int, ...]:
        return tuple(int(value.strip()) for value in self.ai_checkpoint_minutes.split(","))

    @property
    def raybet_discovery_match_types(self) -> tuple[int, ...]:
        return tuple(int(value.strip()) for value in self.raybet_match_types.split(","))

    @property
    def raybet_http_hosts(self) -> tuple[str, ...]:
        raw = self.raybet_info_base_urls.strip()
        if raw:
            return tuple(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
        if self.raybet_info_base_url:
            return (self.raybet_info_base_url.strip().rstrip("/"),)
        return DEFAULT_RAYBET_INFO_BASE_URLS

    @property
    def future_odds_horizons(self) -> tuple[int, ...]:
        return tuple(int(value.strip()) for value in self.future_odds_horizons_seconds.split(","))

    @property
    def decision_email_recipients(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.email_recipients.split(",") if value.strip())

    @property
    def email_configuration_errors(self) -> tuple[str, ...]:
        if not self.email_notifications_enabled:
            return ()
        missing = []
        if self.resend_api_key is None:
            missing.append("RESEND_API_KEY")
        if not self.resend_from:
            missing.append("RESEND_FROM")
        if not self.decision_email_recipients:
            missing.append("EMAIL_RECIPIENTS")
        return tuple(missing)


@lru_cache
def get_settings() -> Settings:
    return Settings()
