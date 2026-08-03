"""Strategy Greek aggregation and efficiency scores."""

from __future__ import annotations

from typing import Optional, Sequence

from app.schemas.strategy import OptionLeg, StrategyCandidate


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def aggregate_strategy_greeks(legs: Sequence[OptionLeg]) -> dict[str, float]:
    """
    Sum signed Greeks across legs.

    Buy = +quantity, sell = -quantity. Provider Greeks treated as per-share;
    multiplied by 100 for per-contract style totals.
    """
    delta = gamma = theta = vega = 0.0
    for leg in legs:
        sign = 1 if leg.action == "buy" else -1
        qty = leg.quantity * sign
        if leg.delta is not None:
            delta += qty * leg.delta * 100
        if leg.gamma is not None:
            gamma += qty * leg.gamma * 100
        if leg.theta is not None:
            theta += qty * leg.theta * 100
        if leg.vega is not None:
            vega += qty * leg.vega * 100
    return {
        "delta": round(delta, 2),
        "gamma": round(gamma, 4),
        "theta": round(theta, 2),
        "vega": round(vega, 2),
    }


def greek_efficiency_score(
    candidate: StrategyCandidate,
    *,
    profile: str = "short_premium",
) -> float:
    """
    Overlay score 0–100 from Greek shape.

    Short premium: reward theta, penalize gamma/delta/short DTE.
    Long vol: reward vega/gamma, penalize theta burn.
    """
    greeks = candidate.greek_summary or aggregate_strategy_greeks(candidate.legs)
    delta = abs(float(greeks.get("delta") or 0.0))
    gamma = abs(float(greeks.get("gamma") or 0.0))
    theta = float(greeks.get("theta") or 0.0)
    vega = abs(float(greeks.get("vega") or 0.0))
    spot = candidate.underlying_price or 0.0
    gamma_risk = abs(spot * gamma) if spot else gamma * 100

    score = 50.0

    if profile == "long_vol":
        # Reward convexity, penalize theta burn.
        if vega > 0:
            score += clamp(vega / 5.0, 0, 15)
        if gamma_risk > 0:
            score += clamp(gamma_risk / 50.0, 0, 10)
        if theta < 0:
            score -= clamp(abs(theta) / 5.0, 0, 20)
        if candidate.dte < 14:
            score -= 10
    else:
        # Short premium default.
        if theta > 0:
            score += clamp(theta / 5.0, 0, 20)
        else:
            score -= clamp(abs(theta) / 5.0, 0, 15)

        # Prefer low net delta for neutral credit structures.
        if candidate.strategy_type in {
            "bull_put_credit",
            "bear_call_credit",
            "iron_condor",
        }:
            if delta < 10:
                score += 15
            elif delta < 25:
                score += 8
            else:
                score -= clamp((delta - 25) / 5.0, 0, 15)
        else:
            # Directional debit spreads can carry delta.
            if delta < 40:
                score += 8

        if gamma_risk < 20:
            score += 15
        elif gamma_risk < 50:
            score += 8
        else:
            score -= clamp((gamma_risk - 50) / 20.0, 0, 15)

        if candidate.dte < 7:
            score -= 20
        elif candidate.dte < 14:
            score -= 10

    return round(clamp(score, 0, 100), 1)
