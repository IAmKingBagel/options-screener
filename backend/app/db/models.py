"""Database models for stored option chain snapshots."""

import json
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ChainSnapshotRun(Base):
    """Metadata for one option chain fetch and store operation."""

    __tablename__ = "chain_snapshot_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    underlying_symbol: Mapped[str] = mapped_column(String(32), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="massive")
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    contracts: Mapped[list["StoredOptionContract"]] = relationship(
        back_populates="snapshot_run",
        cascade="all, delete-orphan",
    )


class StoredOptionContract(Base):
    """Persisted normalized option contract from a snapshot run."""

    __tablename__ = "stored_option_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_run_id: Mapped[int] = mapped_column(ForeignKey("chain_snapshot_runs.id"), index=True)

    symbol: Mapped[str] = mapped_column(String(64), index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(32), index=True)
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_type: Mapped[str] = mapped_column(String(8))
    expiration_date: Mapped[date] = mapped_column(Date, index=True)
    strike: Mapped[float] = mapped_column(Float)
    dte: Mapped[int] = mapped_column(Integer)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_abs: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    implied_volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)
    break_even: Mapped[float | None] = mapped_column(Float, nullable=True)
    exercise_style: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quote_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trade_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="massive")
    raw_provider_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    snapshot_run: Mapped["ChainSnapshotRun"] = relationship(back_populates="contracts")

    @staticmethod
    def serialize_raw(payload: dict | None) -> str | None:
        if payload is None:
            return None
        return json.dumps(payload)

    @staticmethod
    def deserialize_raw(payload_json: str | None) -> dict | None:
        if not payload_json:
            return None
        return json.loads(payload_json)


class UnderlyingDailyClose(Base):
    """Stored daily close prices for realized-vol calculations."""

    __tablename__ = "underlying_daily_closes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        # One close per symbol per day
        {"sqlite_autoincrement": True},
    )


class IvSnapshotHistory(Base):
    """Daily IV30 snapshots used for IV Rank / IV Percentile."""

    __tablename__ = "iv_snapshot_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    iv30: Mapped[float] = mapped_column(Float)
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_rv_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    vrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TrackedCandidate(Base):
    """User-saved strategy candidate for forward outcome tracking."""

    __tablename__ = "tracked_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy_type: Mapped[str] = mapped_column(String(32))
    expiration_date: Mapped[date] = mapped_column(Date, index=True)
    dte_at_entry: Mapped[int] = mapped_column(Integer)
    legs_json: Mapped[str] = mapped_column(Text)
    legs_summary: Mapped[str] = mapped_column(String(256))
    entry_net: Mapped[float] = mapped_column(Float)
    is_credit: Mapped[bool] = mapped_column(Boolean, default=True)
    max_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_alpha: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_grade: Mapped[str | None] = mapped_column(String(8), nullable=True)
    entry_ev_physical: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_pop_physical: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_liquidity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    tracked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_mark_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pnl_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_3d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_14d: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_50pct_profit: Mapped[bool] = mapped_column(Boolean, default=False)
    hit_max_loss: Mapped[bool] = mapped_column(Boolean, default=False)

    marks: Mapped[list["CandidateMark"]] = relationship(
        back_populates="tracked_candidate",
        cascade="all, delete-orphan",
    )


class CandidateMark(Base):
    """Point-in-time mark-to-market snapshot for a tracked candidate."""

    __tablename__ = "candidate_marks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_candidates.id"), index=True
    )
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    days_since_entry: Mapped[int] = mapped_column(Integer)
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mark_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct_of_max_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracked_candidate: Mapped["TrackedCandidate"] = relationship(back_populates="marks")
