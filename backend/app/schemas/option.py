"""Normalized option contract schemas."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OptionContractSnapshot(BaseModel):
    """Internal normalized representation of one option contract."""

    symbol: str
    underlying_symbol: str
    underlying_price: Optional[float] = None
    contract_type: Literal["call", "put"]
    expiration_date: date
    strike: float
    dte: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    mid: Optional[float] = None
    spread_abs: Optional[float] = None
    spread_pct: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    implied_volatility: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    break_even: Optional[float] = None
    exercise_style: Optional[str] = None
    quote_timestamp: Optional[datetime] = None
    trade_timestamp: Optional[datetime] = None
    provider: str = "massive"
    raw_provider_payload: Optional[dict] = None
    has_live_quote: bool = False
    # Phase 2 liquidity analytics
    moneyness: Optional[float] = None
    liquidity_score: Optional[float] = None
    quote_age_minutes: Optional[float] = None
    passes_liquidity: bool = True
    contract_warnings: list[str] = Field(default_factory=list)


class OptionChainResponse(BaseModel):
    """API response for a full option chain fetch."""

    underlying_symbol: str
    underlying_price: Optional[float] = None
    fetched_at: datetime
    provider: str = "massive"
    snapshot_id: Optional[int] = None
    from_cache: bool = False
    contract_count: int
    liquid_contract_count: Optional[int] = None
    rejected_contract_count: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)
    contracts: list[OptionContractSnapshot]
