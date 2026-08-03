"""Persist normalized option chain snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import ChainSnapshotRun, StoredOptionContract
from app.schemas.option import OptionContractSnapshot


def store_chain_snapshot(
    db: Session,
    *,
    underlying_symbol: str,
    underlying_price: float | None,
    contracts: list[OptionContractSnapshot],
    raw_payload: dict | None = None,
    provider: str = "massive",
) -> ChainSnapshotRun:
    """Save a snapshot run and all normalized contracts."""
    run = ChainSnapshotRun(
        underlying_symbol=underlying_symbol.upper(),
        fetched_at=datetime.now(timezone.utc),
        provider=provider,
        underlying_price=underlying_price,
        contract_count=len(contracts),
        raw_response_json=json.dumps(raw_payload) if raw_payload else None,
    )
    db.add(run)
    db.flush()

    for contract in contracts:
        db.add(
            StoredOptionContract(
                snapshot_run_id=run.id,
                symbol=contract.symbol,
                underlying_symbol=contract.underlying_symbol,
                underlying_price=contract.underlying_price,
                contract_type=contract.contract_type,
                expiration_date=contract.expiration_date,
                strike=contract.strike,
                dte=contract.dte,
                bid=contract.bid,
                ask=contract.ask,
                last=contract.last,
                mid=contract.mid,
                spread_abs=contract.spread_abs,
                spread_pct=contract.spread_pct,
                volume=contract.volume,
                open_interest=contract.open_interest,
                implied_volatility=contract.implied_volatility,
                delta=contract.delta,
                gamma=contract.gamma,
                theta=contract.theta,
                vega=contract.vega,
                break_even=contract.break_even,
                exercise_style=contract.exercise_style,
                quote_timestamp=contract.quote_timestamp,
                trade_timestamp=contract.trade_timestamp,
                provider=contract.provider,
                raw_provider_payload_json=StoredOptionContract.serialize_raw(
                    contract.raw_provider_payload
                ),
            )
        )

    db.commit()
    db.refresh(run)
    return run
