"""Realized volatility and simple forecast models."""

from __future__ import annotations

import math
from statistics import pstdev
from typing import Optional, Sequence


def log_returns(closes: Sequence[float]) -> list[float]:
    """Daily log returns from a close-price series (oldest first)."""
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev is None or curr is None or prev <= 0 or curr <= 0:
            continue
        returns.append(math.log(curr / prev))
    return returns


def realized_vol(closes: Sequence[float], window: int) -> Optional[float]:
    """
    Annualized realized volatility over the last `window` daily returns.

    realized_vol_N = std(daily_log_returns over N days) * sqrt(252)
    Uses population std (pstdev) for a stable small-sample estimate.
    """
    if window <= 1:
        return None
    returns = log_returns(closes)
    if len(returns) < window:
        return None
    sample = returns[-window:]
    if len(sample) < 2:
        return None
    daily_std = pstdev(sample)
    return daily_std * math.sqrt(252)


def weighted_forecast_rv(
    rv10: Optional[float],
    rv20: Optional[float],
    rv60: Optional[float],
) -> Optional[float]:
    """
    Simple v1 forecast of 30-day realized vol.

    forecast_rv_30 = 0.50 * RV10 + 0.30 * RV20 + 0.20 * RV60
    Falls back to available components if some windows are missing.
    """
    components: list[tuple[float, float]] = []
    if rv10 is not None:
        components.append((0.50, rv10))
    if rv20 is not None:
        components.append((0.30, rv20))
    if rv60 is not None:
        components.append((0.20, rv60))
    if not components:
        return None
    weight_sum = sum(w for w, _ in components)
    return sum(w * v for w, v in components) / weight_sum


def har_rv_forecast_placeholder(*_args, **_kwargs) -> None:
    """Reserved for HAR-RV regression once the data pipeline is stable."""
    return None


def variance_risk_premium(
    iv30: Optional[float],
    forecast_rv_30: Optional[float],
) -> Optional[float]:
    """VRP in variance space: IV30^2 - forecast_rv_30^2."""
    if iv30 is None or forecast_rv_30 is None:
        return None
    return (iv30**2) - (forecast_rv_30**2)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def volatility_scores(
    vrp: Optional[float],
    *,
    vrp_history: Optional[Sequence[float]] = None,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Return (vrp_z, vol_score_short, vol_score_long) on a 0–100 scale.

    Without history, treat VRP magnitude in vol-space units as a soft z proxy.
    """
    if vrp is None:
        return None, None, None

    if vrp_history and len(vrp_history) >= 10:
        mean = sum(vrp_history) / len(vrp_history)
        var = sum((x - mean) ** 2 for x in vrp_history) / len(vrp_history)
        std = math.sqrt(var) if var > 0 else None
        vrp_z = (vrp - mean) / std if std else 0.0
    else:
        # Soft proxy: VRP of 0.01 variance (~10 vol points at 20% vol) ~ 1 z.
        vrp_z = vrp / 0.01

    vol_score_short = clamp(50 + 15 * vrp_z, 0, 100)
    vol_score_long = clamp(50 - 15 * vrp_z, 0, 100)
    return vrp_z, vol_score_short, vol_score_long
