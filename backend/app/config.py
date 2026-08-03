"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "options_screener.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    massive_api_key: str = ""
    massive_base_url: str = "https://api.massive.com"
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    chain_cache_ttl_seconds: int = 300
    default_min_dte: int = 14
    default_max_dte: int = 60
    # Strike window around spot (fraction). Bounding strikes keeps ATM strikes in
    # the paginated result and lets a fixed page budget cover every expiration in
    # the DTE window instead of exhausting pages on one expiration's deep strikes.
    chain_strike_band_pct: float = 0.15
    chain_max_pages: int = 10
    # IV30 estimation only needs near-ATM contracts across a few expirations.
    volatility_strike_band_pct: float = 0.10
    volatility_max_pages: int = 4
    min_open_interest: int = 100
    min_volume: int = 10
    max_spread_pct: float = 0.15
    max_spread_pct_warning: float = 0.25
    quote_stale_minutes_short_dte: float = 45.0
    quote_stale_minutes_swing_warning: float = 120.0
    short_dte_threshold: int = 7
    swing_dte_min: int = 14
    # Strategy quality defaults (screening)
    min_credit_to_width: float = 0.20
    min_strategy_liquidity_score: float = 50.0
    require_positive_ev: bool = True
    require_positive_alpha: bool = True
    min_final_score: float = 55.0
    swing_dte_prefer_min: int = 21
    swing_dte_prefer_max: int = 45
    data_delay_warning: str = (
        "Data may be delayed. Use this dashboard for screening and research, "
        "not live execution. Confirm live prices in your brokerage platform before trading."
    )

    @field_validator("massive_api_key", mode="before")
    @classmethod
    def strip_api_key(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
