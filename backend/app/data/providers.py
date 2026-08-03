"""Provider-specific adapters mapping external API payloads to internal schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.analytics.contract_metrics import (
    compute_dte,
    compute_mid,
    compute_spread,
    nanoseconds_to_datetime,
)
from app.schemas.option import OptionContractSnapshot


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_massive_contract(
    raw: dict[str, Any],
    *,
    include_raw_payload: bool = False,
    as_of: Optional[date] = None,
    underlying_price_override: Optional[float] = None,
) -> OptionContractSnapshot:
    """
    Map one Massive option chain snapshot result object to OptionContractSnapshot.

    Documented Massive fields:
    - details.ticker, details.contract_type, details.expiration_date, details.strike_price
    - last_quote.bid/ask/midpoint/last_updated
    - last_trade.price/sip_timestamp
    - greeks.delta/gamma/theta/vega
    - implied_volatility, open_interest, break_even_price
    - underlying_asset.price/ticker
    - day.volume
    """
    details = raw.get("details") or {}
    quote = raw.get("last_quote") or {}
    trade = raw.get("last_trade") or {}
    greeks = raw.get("greeks") or {}
    day = raw.get("day") or {}
    underlying = raw.get("underlying_asset") or {}

    contract_type = str(details.get("contract_type", "")).lower()
    if contract_type not in {"call", "put"}:
        raise ValueError(f"Unsupported contract_type: {contract_type!r}")

    expiration_date = _parse_date(details["expiration_date"])
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    has_live_quote = bid is not None and ask is not None and ask > bid > 0

    mid = _safe_float(quote.get("midpoint")) or compute_mid(bid, ask)
    if mid is None:
        mid = _safe_float(day.get("vwap")) or _safe_float(day.get("close"))

    spread_abs, spread_pct = compute_spread(bid, ask, mid) if has_live_quote else (None, None)

    underlying_price = _safe_float(underlying.get("price")) or underlying_price_override
    quote_timestamp = nanoseconds_to_datetime(quote.get("last_updated"))
    if quote_timestamp is None:
        quote_timestamp = nanoseconds_to_datetime(day.get("last_updated"))

    return OptionContractSnapshot(
        symbol=str(details.get("ticker") or ""),
        underlying_symbol=str(underlying.get("ticker") or "").upper(),
        underlying_price=underlying_price,
        contract_type=contract_type,  # type: ignore[arg-type]
        expiration_date=expiration_date,
        strike=float(details.get("strike_price") or 0),
        dte=compute_dte(expiration_date, as_of=as_of),
        bid=bid,
        ask=ask,
        last=_safe_float(trade.get("price")) or _safe_float(day.get("close")),
        mid=mid,
        spread_abs=spread_abs,
        spread_pct=spread_pct,
        volume=_safe_int(day.get("volume")),
        open_interest=_safe_int(raw.get("open_interest")),
        implied_volatility=_safe_float(raw.get("implied_volatility")),
        delta=_safe_float(greeks.get("delta")),
        gamma=_safe_float(greeks.get("gamma")),
        theta=_safe_float(greeks.get("theta")),
        vega=_safe_float(greeks.get("vega")),
        break_even=_safe_float(raw.get("break_even_price")),
        exercise_style=details.get("exercise_style"),
        quote_timestamp=quote_timestamp,
        trade_timestamp=nanoseconds_to_datetime(trade.get("sip_timestamp")),
        provider="massive",
        has_live_quote=has_live_quote,
        raw_provider_payload=raw if include_raw_payload else None,
    )


def normalize_massive_chain(
    payload: dict[str, Any],
    *,
    include_raw_payload: bool = False,
    as_of: Optional[date] = None,
    underlying_price_override: Optional[float] = None,
) -> tuple[list[OptionContractSnapshot], Optional[float], list[str]]:
    """
    Normalize a full Massive chain payload.

    Returns (contracts, underlying_price, warnings).
    """
    warnings: list[str] = []
    contracts: list[OptionContractSnapshot] = []
    underlying_price: Optional[float] = None

    if underlying_price_override is not None:
        underlying_price = underlying_price_override

    for raw in payload.get("results") or []:
        try:
            contract = normalize_massive_contract(
                raw,
                include_raw_payload=include_raw_payload,
                as_of=as_of,
                underlying_price_override=underlying_price_override,
            )
        except (KeyError, TypeError, ValueError) as exc:
            ticker = (raw.get("details") or {}).get("ticker", "unknown")
            warnings.append(f"Skipped contract {ticker}: {exc}")
            continue

        if contract.underlying_price is not None and underlying_price is None:
            underlying_price = contract.underlying_price
        contracts.append(contract)

    if not any(c.has_live_quote for c in contracts):
        warnings.append(
            "No live bid/ask in API response — liquidity screening uses open interest "
            "and day-bar volume/close. Confirm executable prices in your broker."
        )

    return contracts, underlying_price, warnings
