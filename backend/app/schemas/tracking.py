"""Tracked candidate schemas."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.strategy import OptionLeg, StrategyCandidate


class TrackCandidateRequest(BaseModel):
    candidate: StrategyCandidate


class CandidateMarkOut(BaseModel):
    id: int
    marked_at: datetime
    days_since_entry: int
    underlying_price: Optional[float] = None
    mark_net: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct_of_max_profit: Optional[float] = None
    notes: Optional[str] = None


class TrackedCandidateOut(BaseModel):
    id: int
    strategy_id: str
    underlying_symbol: str
    strategy_type: str
    expiration_date: date
    dte_at_entry: int
    legs: list[OptionLeg]
    legs_summary: str
    entry_net: float
    is_credit: bool
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    entry_underlying_price: Optional[float] = None
    entry_alpha: Optional[float] = None
    entry_final_score: Optional[float] = None
    entry_grade: Optional[str] = None
    entry_ev_physical: Optional[float] = None
    entry_pop_physical: Optional[float] = None
    entry_liquidity_score: Optional[float] = None
    score_breakdown: dict = Field(default_factory=dict)
    explanation: Optional[str] = None
    status: str
    tracked_at: datetime
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None
    latest_pnl: Optional[float] = None
    latest_mark_net: Optional[float] = None
    latest_underlying_price: Optional[float] = None
    latest_marked_at: Optional[datetime] = None
    pnl_1d: Optional[float] = None
    pnl_3d: Optional[float] = None
    pnl_7d: Optional[float] = None
    pnl_14d: Optional[float] = None
    hit_50pct_profit: bool = False
    hit_max_loss: bool = False
    marks: list[CandidateMarkOut] = Field(default_factory=list)
    score_vs_outcome: Optional[str] = None


class TrackedListResponse(BaseModel):
    open: list[TrackedCandidateOut]
    closed: list[TrackedCandidateOut]
    summary: dict = Field(default_factory=dict)
