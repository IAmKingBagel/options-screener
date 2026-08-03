"""Basic contract metrics: mid price, spread, and days to expiration."""

from datetime import date, datetime, timezone
from typing import Optional


def compute_mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    """Mid price from bid/ask; returns None if either side is missing."""
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= bid:
        return None
    return (bid + ask) / 2.0


def compute_spread(
    bid: Optional[float], ask: Optional[float], mid: Optional[float] = None
) -> tuple[Optional[float], Optional[float]]:
    """
    Absolute and percentage bid-ask spread.

    spread_pct = spread_abs / mid when mid > 0.
    """
    if bid is None or ask is None or ask <= bid:
        return None, None
    spread_abs = ask - bid
    effective_mid = mid if mid and mid > 0 else compute_mid(bid, ask)
    if not effective_mid or effective_mid <= 0:
        return spread_abs, None
    return spread_abs, spread_abs / effective_mid


def compute_dte(expiration_date: date, as_of: Optional[date] = None) -> int:
    """Calendar days from as_of (default today UTC) to expiration."""
    reference = as_of or datetime.now(timezone.utc).date()
    return max((expiration_date - reference).days, 0)


def nanoseconds_to_datetime(value: Optional[int]) -> Optional[datetime]:
    """Convert Massive nanosecond epoch timestamps to UTC datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
