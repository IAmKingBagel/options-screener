"""ATM IV estimation, IV30 interpolation, IV Rank and IV Percentile."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional, Sequence

from app.schemas.option import OptionContractSnapshot


def compute_iv_rank(current_iv: float, historical_iv_series: Sequence[float]) -> Optional[float]:
    """
    IV Rank over lookback:
    IVR = (current - min) / (max - min) * 100
    """
    if not historical_iv_series:
        return None
    series_min = min(historical_iv_series)
    series_max = max(historical_iv_series)
    if series_max <= series_min:
        return 50.0 if series_min == current_iv else None
    return (current_iv - series_min) / (series_max - series_min) * 100.0


def compute_iv_percentile(
    current_iv: float,
    historical_iv_series: Sequence[float],
) -> Optional[float]:
    """Percentage of lookback days where historical IV < current IV."""
    if not historical_iv_series:
        return None
    below = sum(1 for value in historical_iv_series if value < current_iv)
    return below / len(historical_iv_series) * 100.0


def estimate_atm_iv(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_price: Optional[float] = None,
    min_open_interest: int = 50,
) -> Optional[float]:
    """
    Estimate ATM IV for a set of contracts (typically one expiration).

    Prefer liquid options with |delta| near 0.50; fall back to strike nearest spot.
    Average call and put ATM IV when both exist.
    """
    liquid = [
        c
        for c in contracts
        if c.implied_volatility is not None
        and c.implied_volatility > 0
        and (c.open_interest or 0) >= min_open_interest
    ]
    if not liquid:
        liquid = [
            c
            for c in contracts
            if c.implied_volatility is not None and c.implied_volatility > 0
        ]
    if not liquid:
        return None

    spot = underlying_price or next(
        (c.underlying_price for c in liquid if c.underlying_price), None
    )

    by_type: dict[str, list[OptionContractSnapshot]] = {"call": [], "put": []}
    for contract in liquid:
        by_type[contract.contract_type].append(contract)

    atm_ivs: list[float] = []
    for side, side_contracts in by_type.items():
        if not side_contracts:
            continue
        with_delta = [
            c
            for c in side_contracts
            if c.delta is not None
        ]
        if with_delta:
            target = 0.50 if side == "call" else -0.50
            best = min(with_delta, key=lambda c: abs((c.delta or 0.0) - target))
            if abs((best.delta or 0.0) - target) <= 0.20:
                atm_ivs.append(best.implied_volatility or 0.0)
                continue

        if spot is not None:
            best = min(side_contracts, key=lambda c: abs(c.strike - spot))
            atm_ivs.append(best.implied_volatility or 0.0)
        else:
            atm_ivs.append(side_contracts[0].implied_volatility or 0.0)

    if not atm_ivs:
        return None
    return sum(atm_ivs) / len(atm_ivs)


def interpolate_iv30(expiration_iv_points: Sequence[tuple[int, float]]) -> Optional[float]:
    """
    Interpolate (or extrapolate lightly) ATM IV to 30 DTE.

    expiration_iv_points: list of (dte, atm_iv), dte > 0.
    """
    points = sorted(
        [(dte, iv) for dte, iv in expiration_iv_points if dte > 0 and iv is not None and iv > 0],
        key=lambda item: item[0],
    )
    if not points:
        return None
    if len(points) == 1:
        return points[0][1]

    target = 30
    # Exact match
    for dte, iv in points:
        if dte == target:
            return iv

    below = [p for p in points if p[0] < target]
    above = [p for p in points if p[0] > target]

    if below and above:
        d1, iv1 = below[-1]
        d2, iv2 = above[0]
        weight = (target - d1) / (d2 - d1)
        return iv1 + weight * (iv2 - iv1)

    # Extrapolate from nearest two points on one side, clamped to nearest.
    if not below:
        return above[0][1]
    return below[-1][1]


def estimate_iv30_from_chain(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_price: Optional[float] = None,
    min_open_interest: int = 50,
) -> tuple[Optional[float], list[tuple[int, float]], list[str]]:
    """
    Build per-expiration ATM IV points and interpolate to IV30.

    Returns (iv30, expiration_points, warnings).
    """
    warnings: list[str] = []
    by_expiry: dict[int, list[OptionContractSnapshot]] = defaultdict(list)
    for contract in contracts:
        if contract.dte <= 0:
            continue
        by_expiry[contract.dte].append(contract)

    points: list[tuple[int, float]] = []
    for dte, group in sorted(by_expiry.items()):
        atm = estimate_atm_iv(
            group,
            underlying_price=underlying_price,
            min_open_interest=min_open_interest,
        )
        if atm is not None:
            points.append((dte, atm))

    if not points:
        warnings.append("Could not estimate ATM IV from chain (missing IV or liquid contracts).")
        return None, [], warnings

    iv30 = interpolate_iv30(points)
    if iv30 is None:
        warnings.append("Could not interpolate IV30 from available expirations.")
    return iv30, points, warnings


def history_status(snapshot_count: int) -> str:
    """Human-readable IV history sufficiency label."""
    if snapshot_count >= 252:
        return "full_52w"
    if snapshot_count >= 120:
        return "limited_120d"
    if snapshot_count >= 60:
        return "limited_60d"
    if snapshot_count >= 30:
        return "limited_30d"
    if snapshot_count > 0:
        return "limited_history"
    return "no_history"


def iv_regime_label(iv_rank: Optional[float], iv_percentile: Optional[float]) -> str:
    metric = iv_rank if iv_rank is not None else iv_percentile
    if metric is None:
        return "unknown"
    if metric >= 70:
        return "high"
    if metric >= 50:
        return "elevated"
    if metric <= 20:
        return "low"
    return "neutral"
