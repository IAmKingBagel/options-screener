"""Build liquidity settings from application config."""

from app.analytics.liquidity import LiquiditySettings
from app.config import Settings


def liquidity_settings_from_config(settings: Settings) -> LiquiditySettings:
    return LiquiditySettings(
        min_open_interest=settings.min_open_interest,
        min_volume=settings.min_volume,
        max_spread_pct=settings.max_spread_pct,
        max_spread_pct_warning=settings.max_spread_pct_warning,
        quote_stale_minutes_short_dte=settings.quote_stale_minutes_short_dte,
        quote_stale_minutes_swing_warning=settings.quote_stale_minutes_swing_warning,
        short_dte_threshold=settings.short_dte_threshold,
        swing_dte_min=settings.swing_dte_min,
        require_volume=False,
    )
