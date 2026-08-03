"""Volatility metrics API schemas."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class VolatilityMetrics(BaseModel):
    symbol: str
    as_of: datetime
    underlying_price: Optional[float] = None

    realized_vol_10d: Optional[float] = None
    realized_vol_20d: Optional[float] = None
    realized_vol_30d: Optional[float] = None
    realized_vol_60d: Optional[float] = None
    forecast_rv_30d: Optional[float] = None

    iv30: Optional[float] = None
    atm_iv_points: list[tuple[int, float]] = Field(default_factory=list)

    iv_rank_52w: Optional[float] = None
    iv_percentile_52w: Optional[float] = None
    iv_history_count: int = 0
    iv_history_status: str = "no_history"
    iv_regime: str = "unknown"

    vrp: Optional[float] = None
    vrp_z: Optional[float] = None
    vol_score_short: Optional[float] = None
    vol_score_long: Optional[float] = None

    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DailyCloseBar(BaseModel):
    date: date
    close: float
