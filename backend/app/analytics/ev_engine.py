"""Attach physical and risk-neutral EV / POP / Alpha to strategy candidates."""

from __future__ import annotations

from typing import Optional

from app.analytics.payoff import strategy_payoff_grid
from app.analytics.probability import (
    alpha_from_ev,
    expected_value_from_grid,
    lognormal_probabilities,
    probability_profit,
    terminal_price_grid,
)
from app.schemas.strategy import StrategyCandidate


def _strategy_iv(candidate: StrategyCandidate) -> Optional[float]:
    ivs = [
        leg.implied_volatility
        for leg in candidate.legs
        if leg.implied_volatility is not None and leg.implied_volatility > 0
    ]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def score_candidate_ev(
    candidate: StrategyCandidate,
    *,
    forecast_rv: Optional[float],
    iv30: Optional[float] = None,
    commission_per_contract: float = 0.65,
    n_points: int = 800,
) -> StrategyCandidate:
    """
    Compute EV/POP/Alpha under physical (forecast RV) and risk-neutral (IV) models.

    Payoffs are per share; max_loss is per share — Alpha is unitless.
    """
    spot = candidate.underlying_price
    if spot is None or spot <= 0 or not candidate.legs:
        candidate.warnings.append("EV skipped: missing underlying price")
        return candidate

    physical_vol = forecast_rv
    rn_vol = iv30 if iv30 is not None else _strategy_iv(candidate)

    if physical_vol is None and rn_vol is None:
        candidate.warnings.append("EV skipped: no forecast RV or IV available")
        return candidate

    # Use the larger vol for grid range so both models are covered.
    grid_vol = max(v for v in (physical_vol, rn_vol) if v is not None)
    prices = terminal_price_grid(
        spot, grid_vol, candidate.dte, n_points=n_points
    )
    payoffs = strategy_payoff_grid(
        candidate.legs,
        prices,
        commission_per_contract=commission_per_contract,
    )

    if physical_vol is not None:
        probs_p = lognormal_probabilities(
            prices, spot=spot, annual_vol=physical_vol, dte=candidate.dte, drift=0.0
        )
        candidate.ev_physical = expected_value_from_grid(payoffs, probs_p)
        candidate.pop_physical = probability_profit(payoffs, probs_p)
        candidate.alpha = alpha_from_ev(candidate.ev_physical, candidate.max_loss)

    if rn_vol is not None:
        probs_rn = lognormal_probabilities(
            prices, spot=spot, annual_vol=rn_vol, dte=candidate.dte, drift=0.0
        )
        candidate.ev_risk_neutral = expected_value_from_grid(payoffs, probs_rn)
        candidate.pop_risk_neutral = probability_profit(payoffs, probs_rn)

    # Keep a compact payoff sample for charts (downsample).
    step = max(len(prices) // 50, 1)
    candidate.payoff_curve = [
        {"price": round(prices[i], 4), "payoff": round(payoffs[i], 4)}
        for i in range(0, len(prices), step)
    ]

    if candidate.alpha is not None:
        if candidate.alpha > 0:
            candidate.explanation += (
                f" Modeled physical Alpha={candidate.alpha:.3f} "
                f"(EV={candidate.ev_physical:.3f} / max_loss={candidate.max_loss:.3f})."
            )
        else:
            candidate.explanation += (
                f" Modeled physical Alpha={candidate.alpha:.3f} (non-positive expectancy "
                "under forecast RV)."
            )
            candidate.warnings.append("Non-positive modeled EV under forecast RV")

    if (
        candidate.pop_physical is not None
        and candidate.ev_physical is not None
        and candidate.pop_physical > 0.6
        and candidate.ev_physical < 0
    ):
        candidate.warnings.append("High POP but negative EV — asymmetric losses")

    return candidate


def score_candidates_ev(
    candidates: list[StrategyCandidate],
    *,
    forecast_rv: Optional[float],
    iv30: Optional[float] = None,
    commission_per_contract: float = 0.65,
) -> list[StrategyCandidate]:
    return [
        score_candidate_ev(
            candidate,
            forecast_rv=forecast_rv,
            iv30=iv30,
            commission_per_contract=commission_per_contract,
        )
        for candidate in candidates
    ]
