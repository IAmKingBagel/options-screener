"""Underlying-level snapshot schema (expanded in later phases)."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class UnderlyingSnapshot(BaseModel):
    symbol: str
    price: float
    timestamp: datetime
    historical_close_series: Optional[list[float]] = None
    realized_vol_10d: Optional[float] = None
    realized_vol_20d: Optional[float] = None
    realized_vol_30d: Optional[float] = None
    realized_vol_60d: Optional[float] = None
    forecast_rv_30d: Optional[float] = None
    iv30: Optional[float] = None
    iv_rank_52w: Optional[float] = None
    iv_percentile_52w: Optional[float] = None
    earnings_date: Optional[date] = None
    dividend_date: Optional[date] = None
