"""Strategy candidate schemas."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OptionLeg(BaseModel):
    contract_symbol: str
    action: Literal["buy", "sell"]
    quantity: int = 1
    contract_type: Literal["call", "put"]
    strike: float
    expiration_date: date
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    price_used: float
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    implied_volatility: Optional[float] = None
    open_interest: Optional[int] = None


class StrategyCandidate(BaseModel):
    strategy_id: str
    underlying_symbol: str
    underlying_price: Optional[float] = None
    strategy_type: str
    expiration_date: date
    dte: int
    legs: list[OptionLeg]
    legs_summary: str
    net_debit_or_credit: float
    is_credit: bool
    mid_net: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: list[float] = Field(default_factory=list)
    credit_to_width: Optional[float] = None
    width: Optional[float] = None
    liquidity_score: float = 0.0
    greek_summary: dict = Field(default_factory=dict)
    # Phase 5 — EV / POP / Alpha
    ev_physical: Optional[float] = None
    ev_risk_neutral: Optional[float] = None
    pop_physical: Optional[float] = None
    pop_risk_neutral: Optional[float] = None
    alpha: Optional[float] = None
    payoff_curve: list[dict] = Field(default_factory=list)
    # Phase 6 — composite scoring
    greek_score: Optional[float] = None
    score_breakdown: dict = Field(default_factory=dict)
    final_score: Optional[float] = None
    grade: Optional[str] = None
    scoring_profile: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    explanation: str = ""


class ScreenRequest(BaseModel):
    symbols: list[str]
    strategy_types: list[str] = Field(
        default_factory=lambda: [
            "bull_put_credit",
            "bear_call_credit",
            "iron_condor",
            "bull_call_debit",
            "bear_put_debit",
        ]
    )
    dte_min: int = 14
    dte_max: int = 60
    include_rejected_legs: bool = False
    force_refresh: bool = False
    max_candidates_per_strategy: int = 20
    scoring_profile: str = "auto"
    max_risk_per_trade: Optional[float] = None


class ScreenResponse(BaseModel):
    candidates: list[StrategyCandidate]
    warnings: list[str] = Field(default_factory=list)
    symbols_scanned: list[str] = Field(default_factory=list)
