from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RAYBET_INFO_BASE_URLS = (
    "https://cfinfo.365raylinks.com/v2",
    "https://iminfo.esportsworldlink.com/v2",
    "https://cfinfo.365raylines.com/v2",
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        validate_assignment=True,
    )

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
    openai_reasoning_effort: str = "high"
    # Optional local OpenAI-compatible proxy (Ollama, LiteLLM, ...). It votes as
    # an independent GPT provider named local_openai whenever the key is set.
    local_openai_api_key: SecretStr | None = None
    local_openai_base_url: str = "http://localhost:11434/v1"
    local_openai_model: str = "local-model"
    local_openai_reasoning_effort: str = "high"
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
    # Kimi votes in decisions only while enabled; disabled by default for low latency.
    # The key stays configured so it can be re-enabled without touching credentials.
    kimi_decisions_enabled: bool = False
    ai_timeout_seconds: float = 50.0
    # Delayed DLTV broadcast data beyond this lag is excluded from the AI input
    # (the decision then uses only freeze-time consistent information).
    ai_max_live_data_lag_seconds: float = 120.0
    # Each provider/model owns an independent virtual shadow bankroll per match.
    # Models choose a virtual stake within the available bankroll; no real money
    # and no automatic execution exist in V1.
    ai_virtual_bankroll: float = Field(default=10_000.0, gt=0)
    # Number of recent prior rounds exposed in the prompt context. Every
    # canonical prior round still counts toward the virtual bankroll.
    ai_prior_decisions_limit: int = Field(default=10, ge=1)
    # The deepseek flash model still powers email translation; this flag only
    # controls whether it also produces decision votes (off by default).
    deepseek_flash_decisions_enabled: bool = False
    # Pro votes by default; set false to temporarily switch decision votes to
    # flash without touching credentials or the email translator.
    deepseek_pro_decisions_enabled: bool = True
    email_translation_reasoning_effort: str = "low"

    email_notifications_enabled: bool = False
    email_recipients: str = ""
    email_subject_prefix: str = "[Dota AI Decision Lab]"
    resend_api_key: SecretStr | None = None
    resend_from: str | None = None
    resend_base_url: str = "https://api.resend.com"
    resend_timeout_seconds: float = Field(default=30.0, gt=0)

    # Official WeChat ClawBot channel (direct iLink HTTP API, no OpenClaw).
    wechat_clawbot_enabled: bool = False
    wechat_clawbot_base_url: str = "https://ilinkai.weixin.qq.com"
    wechat_clawbot_state_dir: str = ".runtime/wechat-clawbot"
    wechat_clawbot_bot_agent: str = "Dota-AI-Decision-Lab/0.1.0"
    wechat_clawbot_timeout_seconds: float = Field(default=15.0, gt=0)
    wechat_clawbot_long_poll_timeout_seconds: float = Field(default=40.0, gt=0)
    # Decision alerts are live signals, not a backlog feed. Old snapshots are
    # discarded even if durable jobs are recovered much later.
    wechat_clawbot_decision_max_age_seconds: float = Field(default=600.0, gt=0)

    # Official QQ Bot channel.  The gateway/bridge process uses the
    # harness-installed ``@tencent-connect/qqbot-nodejs`` SDK; run
    # ``python -m tools.qq_bot login`` once to bind a QQ robot by QR code.
    qq_bot_enabled: bool = False
    # Optional pre-bound credentials.  Normally use the QR login CLI;
    # these env overrides are for non-interactive installs.
    qq_bot_app_id: SecretStr | None = None
    qq_bot_app_secret: SecretStr | None = None
    qq_bot_state_dir: str = ".runtime/qq-bot"
    # Blank means auto-detect the harness profile node_modules first, then the
    # project-local ``qqbot_bridge/node_modules`` install.
    qq_bot_sdk_root: str = ""
    qq_bot_bridge_host: str = "127.0.0.1"
    qq_bot_bridge_port: int = Field(default=18081, ge=1, le=65_535)
    qq_bot_bridge_timeout_seconds: float = Field(default=15.0, gt=0)
    qq_bot_bridge_startup_timeout_seconds: float = Field(default=20.0, gt=0)
    # Decision alerts are live signals, not a backlog feed.
    qq_bot_decision_max_age_seconds: float = Field(default=600.0, gt=0)
    # Comma separated explicit push targets: c2c:<openid> or group:<group_openid>.
    qq_bot_decision_targets: str = ""
    # In groups only react when the bot is @mentioned.
    qq_bot_group_require_mention: bool = True
    # Optional allowlists. Empty = any private chatter may query; groups still
    # follow qq_bot_group_require_mention unless listed as allowed below.
    qq_bot_allowed_c2c: str = ""
    qq_bot_allowed_groups: str = ""

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
    # RayBet socket batches arrive ~20-50s apart even for an active match
    # (odds publish on change; the deciding map's series market updates on a
    # ~40-50s cadence), so a 30s window makes live markets intermittently
    # STALE_LEG. 90s covers the cadence plus one missed batch while still
    # rejecting genuinely dead feeds.
    live_market_max_age_seconds: float = 90.0
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
    # Concurrent RUN_AI_PROVIDER durable jobs. One job = one provider/model, so
    # this is the number of AI HTTP requests that can be in flight at once.
    ai_worker_concurrency: int = Field(default=4, ge=1)
    job_lease_seconds: float = 120.0
    reconciliation_interval_seconds: float = 60.0
    metrics_enabled: bool = True
    otel_exporter_otlp_endpoint: str | None = None
    host: str = "127.0.0.1"
    # Reserved for a future authenticated remote-access mode. It does not
    # unlock non-loopback binding while the dashboard has no auth layer.
    api_token: SecretStr | None = None
    port: int = Field(default=8000, ge=1, le=65_535)
    log_level: str = "INFO"

    @field_validator("host")
    @classmethod
    def require_loopback_host(cls, value: str) -> str:
        if value not in _LOOPBACK_HOSTS:
            raise ValueError(
                "HOST must be loopback until HTTP and WebSocket authentication are implemented"
            )
        return value

    @property
    def checkpoint_minutes(self) -> tuple[int, ...]:
        return tuple(int(value.strip()) for value in self.ai_checkpoint_minutes.split(","))

    @property
    def qq_bot_decision_target_entries(self) -> tuple[str, ...]:
        return _split_non_empty(self.qq_bot_decision_targets)

    @property
    def qq_bot_allowed_c2c_ids(self) -> tuple[str, ...]:
        return _split_non_empty(self.qq_bot_allowed_c2c)

    @property
    def qq_bot_allowed_group_ids(self) -> tuple[str, ...]:
        return _split_non_empty(self.qq_bot_allowed_groups)

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


def _split_non_empty(raw: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in raw.split(",") if value.strip())
