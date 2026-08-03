"""Simple in-memory and database-backed chain response cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ChainSnapshotRun, StoredOptionContract
from app.schemas.option import OptionChainResponse, OptionContractSnapshot


def _contract_to_schema(row: StoredOptionContract) -> OptionContractSnapshot:
    # has_live_quote isn't persisted; derive it from bid/ask with the same rule
    # used at normalization so cached liquidity scoring matches a fresh fetch.
    has_live_quote = (
        row.bid is not None
        and row.ask is not None
        and row.ask > row.bid > 0
    )
    return OptionContractSnapshot(
        symbol=row.symbol,
        underlying_symbol=row.underlying_symbol,
        underlying_price=row.underlying_price,
        contract_type=row.contract_type,  # type: ignore[arg-type]
        expiration_date=row.expiration_date,
        strike=row.strike,
        dte=row.dte,
        bid=row.bid,
        ask=row.ask,
        has_live_quote=has_live_quote,
        last=row.last,
        mid=row.mid,
        spread_abs=row.spread_abs,
        spread_pct=row.spread_pct,
        volume=row.volume,
        open_interest=row.open_interest,
        implied_volatility=row.implied_volatility,
        delta=row.delta,
        gamma=row.gamma,
        theta=row.theta,
        vega=row.vega,
        break_even=row.break_even,
        exercise_style=row.exercise_style,
        quote_timestamp=row.quote_timestamp,
        trade_timestamp=row.trade_timestamp,
        provider=row.provider,
        raw_provider_payload=StoredOptionContract.deserialize_raw(row.raw_provider_payload_json),
    )


def get_recent_snapshot(
    db: Session,
    underlying_symbol: str,
    ttl_seconds: Optional[int] = None,
) -> Optional[OptionChainResponse]:
    """Return cached chain if a recent snapshot exists within TTL."""
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.chain_cache_ttl_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl)

    stmt = (
        select(ChainSnapshotRun)
        .where(
            ChainSnapshotRun.underlying_symbol == underlying_symbol.upper(),
            ChainSnapshotRun.fetched_at >= cutoff,
        )
        .order_by(desc(ChainSnapshotRun.fetched_at))
        .limit(1)
    )
    run = db.scalar(stmt)
    if run is None:
        return None

    contracts = [
        _contract_to_schema(row)
        for row in db.scalars(
            select(StoredOptionContract).where(StoredOptionContract.snapshot_run_id == run.id)
        )
    ]

    settings = get_settings()
    return OptionChainResponse(
        underlying_symbol=run.underlying_symbol,
        underlying_price=run.underlying_price,
        fetched_at=run.fetched_at,
        provider=run.provider,
        snapshot_id=run.id,
        from_cache=True,
        contract_count=len(contracts),
        warnings=[settings.data_delay_warning],
        contracts=contracts,
    )
