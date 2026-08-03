"""Lognormal terminal-price probabilities and EV/POP from payoff grids."""

from __future__ import annotations

import math
from typing import Optional, Sequence


def terminal_price_grid(
    spot: float,
    annual_vol: float,
    dte: int,
    *,
    n_points: int = 1000,
    sigma_mult: float = 4.0,
) -> list[float]:
    """
    Evenly spaced terminal prices around spot.

    Range: spot * (1 ± sigma_mult * annual_vol * sqrt(DTE/365))
    """
    if spot <= 0 or n_points < 2:
        return []
    t_years = max(dte, 1) / 365.0
    move = sigma_mult * max(annual_vol, 1e-6) * math.sqrt(t_years)
    lower = max(spot * (1.0 - move), spot * 0.01)
    upper = spot * (1.0 + move)
    if upper <= lower:
        upper = lower * 1.01
    step = (upper - lower) / (n_points - 1)
    return [lower + i * step for i in range(n_points)]


def lognormal_probabilities(
    prices: Sequence[float],
    *,
    spot: float,
    annual_vol: float,
    dte: int,
    drift: float = 0.0,
) -> list[float]:
    """
    Discrete probabilities for terminal prices under a lognormal model.

    Uses the density of ln(S_T) ~ Normal(mu, sigma^2) with
    mu = ln(S0) + (drift - 0.5*vol^2)*T, sigma = vol*sqrt(T).
    Probabilities are normalized to sum to 1.
    """
    if not prices or spot <= 0:
        return []
    t_years = max(dte, 1) / 365.0
    vol = max(annual_vol, 1e-6)
    sigma = vol * math.sqrt(t_years)
    mu = math.log(spot) + (drift - 0.5 * vol * vol) * t_years

    # Midpoint-style bin widths in price space.
    densities: list[float] = []
    for i, price in enumerate(prices):
        if price <= 0:
            densities.append(0.0)
            continue
        if i == 0:
            width = prices[1] - prices[0] if len(prices) > 1 else price * 0.01
        elif i == len(prices) - 1:
            width = prices[i] - prices[i - 1]
        else:
            width = 0.5 * (prices[i + 1] - prices[i - 1])
        # Lognormal pdf for S: 1/(S*sigma*sqrt(2pi)) * exp(-(ln S - mu)^2 / (2 sigma^2))
        z = (math.log(price) - mu) / sigma
        pdf = math.exp(-0.5 * z * z) / (price * sigma * math.sqrt(2.0 * math.pi))
        densities.append(max(pdf * width, 0.0))

    total = sum(densities)
    if total <= 0:
        n = len(prices)
        return [1.0 / n] * n
    return [d / total for d in densities]


def expected_value_from_grid(
    payoffs: Sequence[float],
    probabilities: Sequence[float],
) -> Optional[float]:
    if not payoffs or len(payoffs) != len(probabilities):
        return None
    return sum(p * pay for p, pay in zip(probabilities, payoffs))


def probability_profit(
    payoffs: Sequence[float],
    probabilities: Sequence[float],
) -> Optional[float]:
    if not payoffs or len(payoffs) != len(probabilities):
        return None
    return sum(prob for pay, prob in zip(payoffs, probabilities) if pay > 0)


def probability_itm(
    prices: Sequence[float],
    probabilities: Sequence[float],
    *,
    strike: float,
    contract_type: str,
) -> Optional[float]:
    if not prices or len(prices) != len(probabilities):
        return None
    if contract_type == "call":
        return sum(prob for price, prob in zip(prices, probabilities) if price > strike)
    return sum(prob for price, prob in zip(prices, probabilities) if price < strike)


def alpha_from_ev(ev: Optional[float], max_loss: Optional[float]) -> Optional[float]:
    """Alpha = EV / max_loss (max_loss should be positive risk amount)."""
    if ev is None or max_loss is None or max_loss <= 0:
        return None
    return ev / max_loss
