"""Analytical max profit/loss and breakevens for defined-risk structures."""

from __future__ import annotations

from typing import Optional, Sequence

from app.schemas.strategy import OptionLeg


def option_leg_payoff(
    *,
    contract_type: str,
    strike: float,
    action: str,
    quantity: int,
    entry_price: float,
    terminal_price: float,
) -> float:
    """Payoff for one option leg at expiration, per share (not ×100)."""
    if contract_type == "call":
        intrinsic = max(terminal_price - strike, 0.0)
    else:
        intrinsic = max(strike - terminal_price, 0.0)

    sign = 1 if action == "buy" else -1
    # Buy pays premium; sell receives premium.
    return quantity * sign * (intrinsic - entry_price)


def max_profit_loss_for_vertical(
    *,
    is_credit: bool,
    width: float,
    net_premium: float,
) -> tuple[float, float]:
    """
    Vertical spread max profit / max loss per share.

    net_premium is positive for credit received or debit paid.
    """
    width = abs(width)
    premium = abs(net_premium)
    if is_credit:
        max_profit = premium
        max_loss = width - premium
    else:
        max_profit = width - premium
        max_loss = premium
    return max_profit, max_loss


def max_profit_loss_for_iron_condor(
    *,
    put_width: float,
    call_width: float,
    net_credit: float,
) -> tuple[float, float]:
    """Iron condor max profit / max loss per share (equal or unequal wings)."""
    wing = max(abs(put_width), abs(call_width))
    credit = abs(net_credit)
    max_profit = credit
    max_loss = wing - credit
    return max_profit, max_loss


def breakevens_vertical(
    *,
    strategy_type: str,
    short_strike: float,
    long_strike: float,
    net_premium: float,
    is_credit: bool,
) -> list[float]:
    """Breakeven prices for vertical spreads."""
    premium = abs(net_premium)
    if strategy_type == "bull_put_credit":
        # Short put higher strike; BE = short_strike - credit
        return [short_strike - premium]
    if strategy_type == "bear_call_credit":
        return [short_strike + premium]
    if strategy_type == "bull_call_debit":
        # Long lower strike call; BE = long_strike + debit
        return [long_strike + premium]
    if strategy_type == "bear_put_debit":
        # Long higher strike put; BE = long_strike - debit
        return [long_strike - premium]
    return []


def breakevens_iron_condor(
    *,
    short_put: float,
    short_call: float,
    net_credit: float,
) -> list[float]:
    credit = abs(net_credit)
    return [short_put - credit, short_call + credit]


def credit_to_width(net_credit: float, width: float) -> Optional[float]:
    if width <= 0:
        return None
    return abs(net_credit) / width


def strategy_payoff_grid(
    legs: Sequence[OptionLeg],
    prices: Sequence[float],
    *,
    commission_per_contract: float = 0.0,
    multiplier: float = 1.0,
) -> list[float]:
    """
    Payoff at each terminal price for a multi-leg strategy.

    Default multiplier=1 returns per-share P/L (consistent with max_profit/max_loss).
    Commission is applied once per leg (per share equivalent = commission/100 if
    commission is per contract; pass commission already scaled to per-share if needed).
    """
    commission_per_share = commission_per_contract / 100.0
    payoffs: list[float] = []
    for terminal in prices:
        total = 0.0
        for leg in legs:
            total += option_leg_payoff(
                contract_type=leg.contract_type,
                strike=leg.strike,
                action=leg.action,
                quantity=leg.quantity,
                entry_price=leg.price_used,
                terminal_price=terminal,
            )
            total -= leg.quantity * commission_per_share
        payoffs.append(total * multiplier)
    return payoffs
