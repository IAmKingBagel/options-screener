"""Build defined-risk option strategy candidates from a normalized chain."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional, Sequence
from uuid import uuid4

from app.analytics.liquidity import LiquiditySettings, enrich_contracts
from app.analytics.payoff import (
    breakevens_iron_condor,
    breakevens_vertical,
    credit_to_width,
    max_profit_loss_for_iron_condor,
    max_profit_loss_for_vertical,
)
from app.schemas.option import OptionContractSnapshot
from app.schemas.strategy import OptionLeg, StrategyCandidate


def _leg_price(
    contract: OptionContractSnapshot,
    action: str,
    *,
    slippage: float,
) -> tuple[float, Optional[float], list[str]]:
    """
    Conservative executable price per share.

    Buy: ask, else mid + slippage, else last + slippage.
    Sell: bid, else mid - slippage, else last - slippage.
    """
    warnings: list[str] = []
    mid = contract.mid
    if action == "buy":
        if contract.has_live_quote and contract.ask is not None and contract.ask > 0:
            return contract.ask, mid, warnings
        base = mid if mid is not None else contract.last
        if base is None:
            raise ValueError("No price for buy leg")
        warnings.append("Buy priced from day-bar mid/last + slippage (no live ask)")
        return max(base + slippage, 0.01), mid, warnings

    if contract.has_live_quote and contract.bid is not None and contract.bid > 0:
        return contract.bid, mid, warnings
    base = mid if mid is not None else contract.last
    if base is None:
        raise ValueError("No price for sell leg")
    warnings.append("Sell priced from day-bar mid/last - slippage (no live bid)")
    return max(base - slippage, 0.01), mid, warnings


def _to_leg(
    contract: OptionContractSnapshot,
    action: str,
    *,
    slippage: float,
) -> tuple[OptionLeg, Optional[float], list[str]]:
    price_used, mid, warnings = _leg_price(contract, action, slippage=slippage)
    leg = OptionLeg(
        contract_symbol=contract.symbol,
        action=action,
        quantity=1,
        contract_type=contract.contract_type,
        strike=contract.strike,
        expiration_date=contract.expiration_date,
        bid=contract.bid,
        ask=contract.ask,
        mid=mid,
        price_used=price_used,
        delta=contract.delta,
        gamma=contract.gamma,
        theta=contract.theta,
        vega=contract.vega,
        implied_volatility=contract.implied_volatility,
        open_interest=contract.open_interest,
    )
    return leg, mid, warnings


def _aggregate_greeks(legs: Sequence[OptionLeg]) -> dict:
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


def _liquidity_score(contracts: Sequence[OptionContractSnapshot]) -> float:
    scores = [c.liquidity_score for c in contracts if c.liquidity_score is not None]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _width_tolerance(width: float) -> float:
    """Max allowed deviation of an actual strike from the requested spread width.

    Keeps near-misses (e.g. 19 for a requested 20) but rejects gross mismatches
    (e.g. 1 for a requested 5) that create junk spreads.
    """
    return max(1.0, width * 0.34)


def _wing_widths(underlying_price: Optional[float]) -> list[float]:
    if underlying_price is None or underlying_price < 50:
        return [1.0, 2.5, 5.0]
    if underlying_price < 200:
        return [2.5, 5.0, 10.0]
    if underlying_price < 500:
        return [5.0, 10.0, 15.0]
    return [5.0, 10.0, 20.0, 25.0]


def _group_by_expiry(
    contracts: Sequence[OptionContractSnapshot],
) -> dict[date, list[OptionContractSnapshot]]:
    groups: dict[date, list[OptionContractSnapshot]] = defaultdict(list)
    for contract in contracts:
        groups[contract.expiration_date].append(contract)
    return groups


def _closest_by_abs_delta(
    contracts: Sequence[OptionContractSnapshot],
    target_abs_delta: float,
    *,
    contract_type: str,
    lo: float,
    hi: float,
) -> list[OptionContractSnapshot]:
    candidates = [
        c
        for c in contracts
        if c.contract_type == contract_type
        and c.delta is not None
        and lo <= abs(c.delta) <= hi
    ]
    candidates.sort(key=lambda c: abs(abs(c.delta or 0.0) - target_abs_delta))
    return candidates


def _find_by_strike(
    contracts: Sequence[OptionContractSnapshot],
    strike: float,
    contract_type: str,
    *,
    tolerance: float = 0.01,
    max_distance: Optional[float] = None,
) -> Optional[OptionContractSnapshot]:
    """
    Find a contract at (or nearest to) the target strike.

    If max_distance is set, the nearest strike must be within max_distance of the
    target — otherwise return None. This prevents fabricating mis-specified spread
    widths (e.g. a $1-wide spread when $5 was requested) and stops multiple width
    targets from collapsing onto the same strike (which produced duplicates).
    """
    matches = [
        c
        for c in contracts
        if c.contract_type == contract_type and abs(c.strike - strike) <= tolerance
    ]
    if matches:
        return matches[0]

    typed = [c for c in contracts if c.contract_type == contract_type]
    if not typed:
        return None
    nearest = min(typed, key=lambda c: abs(c.strike - strike))
    if max_distance is not None and abs(nearest.strike - strike) > max_distance:
        return None
    return nearest


def _make_candidate(
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    strategy_type: str,
    legs: list[OptionLeg],
    contracts: list[OptionContractSnapshot],
    net: float,
    mid_net: Optional[float],
    is_credit: bool,
    max_profit: float,
    max_loss: float,
    breakevens: list[float],
    width: Optional[float],
    warnings: list[str],
    explanation: str,
) -> StrategyCandidate:
    expiration = legs[0].expiration_date
    dte = contracts[0].dte
    summary_parts = [
        f"{'S' if leg.action == 'sell' else 'B'}{leg.strike:g}{leg.contract_type[0].upper()}"
        for leg in legs
    ]
    return StrategyCandidate(
        strategy_id=f"{strategy_type}-{uuid4().hex[:10]}",
        underlying_symbol=underlying_symbol,
        underlying_price=underlying_price,
        strategy_type=strategy_type,
        expiration_date=expiration,
        dte=dte,
        legs=legs,
        legs_summary=" / ".join(summary_parts),
        net_debit_or_credit=round(net, 4),
        is_credit=is_credit,
        mid_net=round(mid_net, 4) if mid_net is not None else None,
        max_profit=round(max_profit, 4),
        max_loss=round(max_loss, 4),
        breakevens=[round(b, 4) for b in breakevens],
        credit_to_width=credit_to_width(net, width) if width and is_credit else None,
        width=width,
        liquidity_score=round(_liquidity_score(contracts), 1),
        greek_summary=_aggregate_greeks(legs),
        warnings=warnings,
        explanation=explanation,
    )


def build_bull_put_spreads(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    slippage: float = 0.02,
    min_credit_to_width: float = 0.20,
    max_candidates: int = 20,
) -> list[StrategyCandidate]:
    """Sell OTM put, buy farther OTM put (lower strike)."""
    results: list[StrategyCandidate] = []
    widths = _wing_widths(underlying_price)

    for _expiry, group in _group_by_expiry(contracts).items():
        shorts = _closest_by_abs_delta(
            group, 0.25, contract_type="put", lo=0.20, hi=0.32
        )[:5]
        for short in shorts:
            for width in widths:
                long_strike = short.strike - width
                long = _find_by_strike(
                    group, long_strike, "put", max_distance=_width_tolerance(width)
                )
                if long is None or long.strike >= short.strike:
                    continue
                actual_width = short.strike - long.strike
                if actual_width <= 0:
                    continue
                try:
                    sell_leg, sell_mid, w1 = _to_leg(short, "sell", slippage=slippage)
                    buy_leg, buy_mid, w2 = _to_leg(long, "buy", slippage=slippage)
                except ValueError:
                    continue
                net = sell_leg.price_used - buy_leg.price_used
                if net <= 0:
                    continue
                ctw = credit_to_width(net, actual_width)
                if ctw is None or ctw < min_credit_to_width:
                    continue
                max_profit, max_loss = max_profit_loss_for_vertical(
                    is_credit=True, width=actual_width, net_premium=net
                )
                if max_loss <= 0:
                    continue
                mid_net = None
                if sell_mid is not None and buy_mid is not None:
                    mid_net = sell_mid - buy_mid
                results.append(
                    _make_candidate(
                        underlying_symbol=underlying_symbol,
                        underlying_price=underlying_price,
                        strategy_type="bull_put_credit",
                        legs=[sell_leg, buy_leg],
                        contracts=[short, long],
                        net=net,
                        mid_net=mid_net,
                        is_credit=True,
                        max_profit=max_profit,
                        max_loss=max_loss,
                        breakevens=breakevens_vertical(
                            strategy_type="bull_put_credit",
                            short_strike=short.strike,
                            long_strike=long.strike,
                            net_premium=net,
                            is_credit=True,
                        ),
                        width=actual_width,
                        warnings=w1 + w2,
                        explanation=(
                            "Bull put credit spread: neutral-to-bullish premium collection "
                            f"with defined risk. Credit/width={ctw:.2f}."
                        ),
                    )
                )

    results.sort(key=lambda c: (c.credit_to_width or 0, c.liquidity_score), reverse=True)
    return results[:max_candidates]


def build_bear_call_spreads(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    slippage: float = 0.02,
    min_credit_to_width: float = 0.20,
    max_candidates: int = 20,
) -> list[StrategyCandidate]:
    """Sell OTM call, buy farther OTM call (higher strike)."""
    results: list[StrategyCandidate] = []
    widths = _wing_widths(underlying_price)

    for _expiry, group in _group_by_expiry(contracts).items():
        shorts = _closest_by_abs_delta(
            group, 0.25, contract_type="call", lo=0.20, hi=0.32
        )[:5]
        for short in shorts:
            for width in widths:
                long_strike = short.strike + width
                long = _find_by_strike(
                    group, long_strike, "call", max_distance=_width_tolerance(width)
                )
                if long is None or long.strike <= short.strike:
                    continue
                actual_width = long.strike - short.strike
                try:
                    sell_leg, sell_mid, w1 = _to_leg(short, "sell", slippage=slippage)
                    buy_leg, buy_mid, w2 = _to_leg(long, "buy", slippage=slippage)
                except ValueError:
                    continue
                net = sell_leg.price_used - buy_leg.price_used
                if net <= 0:
                    continue
                ctw = credit_to_width(net, actual_width)
                if ctw is None or ctw < min_credit_to_width:
                    continue
                max_profit, max_loss = max_profit_loss_for_vertical(
                    is_credit=True, width=actual_width, net_premium=net
                )
                if max_loss <= 0:
                    continue
                mid_net = None
                if sell_mid is not None and buy_mid is not None:
                    mid_net = sell_mid - buy_mid
                results.append(
                    _make_candidate(
                        underlying_symbol=underlying_symbol,
                        underlying_price=underlying_price,
                        strategy_type="bear_call_credit",
                        legs=[sell_leg, buy_leg],
                        contracts=[short, long],
                        net=net,
                        mid_net=mid_net,
                        is_credit=True,
                        max_profit=max_profit,
                        max_loss=max_loss,
                        breakevens=breakevens_vertical(
                            strategy_type="bear_call_credit",
                            short_strike=short.strike,
                            long_strike=long.strike,
                            net_premium=net,
                            is_credit=True,
                        ),
                        width=actual_width,
                        warnings=w1 + w2,
                        explanation=(
                            "Bear call credit spread: neutral-to-bearish premium collection "
                            f"with defined risk. Credit/width={ctw:.2f}."
                        ),
                    )
                )

    results.sort(key=lambda c: (c.credit_to_width or 0, c.liquidity_score), reverse=True)
    return results[:max_candidates]


def build_bull_call_debit_spreads(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    slippage: float = 0.02,
    max_candidates: int = 20,
) -> list[StrategyCandidate]:
    """Buy call (delta ~0.5–0.7), sell higher strike call."""
    results: list[StrategyCandidate] = []
    widths = _wing_widths(underlying_price)

    for _expiry, group in _group_by_expiry(contracts).items():
        longs = _closest_by_abs_delta(
            group, 0.60, contract_type="call", lo=0.45, hi=0.75
        )[:5]
        for long in longs:
            for width in widths:
                short_strike = long.strike + width
                short = _find_by_strike(
                    group, short_strike, "call", max_distance=_width_tolerance(width)
                )
                if short is None or short.strike <= long.strike:
                    continue
                if short.delta is not None and not (0.15 <= abs(short.delta) <= 0.45):
                    continue
                actual_width = short.strike - long.strike
                try:
                    buy_leg, buy_mid, w1 = _to_leg(long, "buy", slippage=slippage)
                    sell_leg, sell_mid, w2 = _to_leg(short, "sell", slippage=slippage)
                except ValueError:
                    continue
                net = buy_leg.price_used - sell_leg.price_used
                if net <= 0:
                    continue
                max_profit, max_loss = max_profit_loss_for_vertical(
                    is_credit=False, width=actual_width, net_premium=net
                )
                if max_profit <= 0:
                    continue
                mid_net = None
                if buy_mid is not None and sell_mid is not None:
                    mid_net = buy_mid - sell_mid
                results.append(
                    _make_candidate(
                        underlying_symbol=underlying_symbol,
                        underlying_price=underlying_price,
                        strategy_type="bull_call_debit",
                        legs=[buy_leg, sell_leg],
                        contracts=[long, short],
                        net=net,
                        mid_net=mid_net,
                        is_credit=False,
                        max_profit=max_profit,
                        max_loss=max_loss,
                        breakevens=breakevens_vertical(
                            strategy_type="bull_call_debit",
                            short_strike=short.strike,
                            long_strike=long.strike,
                            net_premium=net,
                            is_credit=False,
                        ),
                        width=actual_width,
                        warnings=w1 + w2,
                        explanation=(
                            "Bull call debit spread: defined-risk bullish structure."
                        ),
                    )
                )

    results.sort(key=lambda c: (c.max_profit or 0) / max(c.max_loss or 1, 1e-6), reverse=True)
    return results[:max_candidates]


def build_bear_put_debit_spreads(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    slippage: float = 0.02,
    max_candidates: int = 20,
) -> list[StrategyCandidate]:
    """Buy put (delta ~-0.5 to -0.7), sell lower strike put."""
    results: list[StrategyCandidate] = []
    widths = _wing_widths(underlying_price)

    for _expiry, group in _group_by_expiry(contracts).items():
        longs = _closest_by_abs_delta(
            group, 0.60, contract_type="put", lo=0.45, hi=0.75
        )[:5]
        for long in longs:
            for width in widths:
                short_strike = long.strike - width
                short = _find_by_strike(
                    group, short_strike, "put", max_distance=_width_tolerance(width)
                )
                if short is None or short.strike >= long.strike:
                    continue
                if short.delta is not None and not (0.15 <= abs(short.delta) <= 0.45):
                    continue
                actual_width = long.strike - short.strike
                try:
                    buy_leg, buy_mid, w1 = _to_leg(long, "buy", slippage=slippage)
                    sell_leg, sell_mid, w2 = _to_leg(short, "sell", slippage=slippage)
                except ValueError:
                    continue
                net = buy_leg.price_used - sell_leg.price_used
                if net <= 0:
                    continue
                max_profit, max_loss = max_profit_loss_for_vertical(
                    is_credit=False, width=actual_width, net_premium=net
                )
                if max_profit <= 0:
                    continue
                mid_net = None
                if buy_mid is not None and sell_mid is not None:
                    mid_net = buy_mid - sell_mid
                results.append(
                    _make_candidate(
                        underlying_symbol=underlying_symbol,
                        underlying_price=underlying_price,
                        strategy_type="bear_put_debit",
                        legs=[buy_leg, sell_leg],
                        contracts=[long, short],
                        net=net,
                        mid_net=mid_net,
                        is_credit=False,
                        max_profit=max_profit,
                        max_loss=max_loss,
                        breakevens=breakevens_vertical(
                            strategy_type="bear_put_debit",
                            short_strike=short.strike,
                            long_strike=long.strike,
                            net_premium=net,
                            is_credit=False,
                        ),
                        width=actual_width,
                        warnings=w1 + w2,
                        explanation=(
                            "Bear put debit spread: defined-risk bearish structure."
                        ),
                    )
                )

    results.sort(key=lambda c: (c.max_profit or 0) / max(c.max_loss or 1, 1e-6), reverse=True)
    return results[:max_candidates]


def build_iron_condors(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    slippage: float = 0.02,
    min_credit_to_width: float = 0.20,
    max_candidates: int = 20,
) -> list[StrategyCandidate]:
    """Short put + long put + short call + long call, equal wings preferred."""
    results: list[StrategyCandidate] = []
    widths = _wing_widths(underlying_price)

    for _expiry, group in _group_by_expiry(contracts).items():
        # Prefer 25–50 DTE for iron condors.
        if group and not (25 <= group[0].dte <= 50):
            # Still allow but warn later.
            pass
        short_puts = _closest_by_abs_delta(
            group, 0.20, contract_type="put", lo=0.12, hi=0.28
        )[:4]
        short_calls = _closest_by_abs_delta(
            group, 0.20, contract_type="call", lo=0.12, hi=0.28
        )[:4]
        for short_put in short_puts:
            for short_call in short_calls:
                if short_call.strike <= short_put.strike:
                    continue
                for width in widths:
                    tol = _width_tolerance(width)
                    long_put = _find_by_strike(
                        group, short_put.strike - width, "put", max_distance=tol
                    )
                    long_call = _find_by_strike(
                        group, short_call.strike + width, "call", max_distance=tol
                    )
                    if long_put is None or long_call is None:
                        continue
                    if long_put.strike >= short_put.strike:
                        continue
                    if long_call.strike <= short_call.strike:
                        continue
                    put_width = short_put.strike - long_put.strike
                    call_width = long_call.strike - short_call.strike
                    try:
                        sp, sp_mid, w1 = _to_leg(short_put, "sell", slippage=slippage)
                        lp, lp_mid, w2 = _to_leg(long_put, "buy", slippage=slippage)
                        sc, sc_mid, w3 = _to_leg(short_call, "sell", slippage=slippage)
                        lc, lc_mid, w4 = _to_leg(long_call, "buy", slippage=slippage)
                    except ValueError:
                        continue
                    net = (sp.price_used + sc.price_used) - (lp.price_used + lc.price_used)
                    if net <= 0:
                        continue
                    wing = max(put_width, call_width)
                    ctw = credit_to_width(net, wing)
                    if ctw is None or ctw < min_credit_to_width:
                        continue
                    max_profit, max_loss = max_profit_loss_for_iron_condor(
                        put_width=put_width,
                        call_width=call_width,
                        net_credit=net,
                    )
                    if max_loss <= 0:
                        continue
                    mid_net = None
                    if None not in (sp_mid, lp_mid, sc_mid, lc_mid):
                        mid_net = (sp_mid + sc_mid) - (lp_mid + lc_mid)
                    warnings = w1 + w2 + w3 + w4
                    if group[0].dte < 25 or group[0].dte > 50:
                        warnings.append("Iron condor outside preferred 25–50 DTE")
                    results.append(
                        _make_candidate(
                            underlying_symbol=underlying_symbol,
                            underlying_price=underlying_price,
                            strategy_type="iron_condor",
                            legs=[sp, lp, sc, lc],
                            contracts=[short_put, long_put, short_call, long_call],
                            net=net,
                            mid_net=mid_net,
                            is_credit=True,
                            max_profit=max_profit,
                            max_loss=max_loss,
                            breakevens=breakevens_iron_condor(
                                short_put=short_put.strike,
                                short_call=short_call.strike,
                                net_credit=net,
                            ),
                            width=wing,
                            warnings=warnings,
                            explanation=(
                                "Iron condor: neutral short-vol structure with defined risk. "
                                f"Credit/width={ctw:.2f}."
                            ),
                        )
                    )

    results.sort(key=lambda c: (c.credit_to_width or 0, c.liquidity_score), reverse=True)
    return results[:max_candidates]


BUILDERS = {
    "bull_put_credit": build_bull_put_spreads,
    "bear_call_credit": build_bear_call_spreads,
    "bull_call_debit": build_bull_call_debit_spreads,
    "bear_put_debit": build_bear_put_debit_spreads,
    "iron_condor": build_iron_condors,
}


def _dte_in_swing_sweet_spot(dte: int, lo: int = 21, hi: int = 45) -> bool:
    return lo <= dte <= hi


def build_strategies(
    contracts: Sequence[OptionContractSnapshot],
    *,
    underlying_symbol: str,
    underlying_price: Optional[float],
    strategy_types: Sequence[str],
    liquidity_settings: Optional[LiquiditySettings] = None,
    slippage: float = 0.02,
    max_candidates_per_strategy: int = 20,
    min_credit_to_width: float = 0.20,
    min_leg_liquidity_score: float = 50.0,
    swing_dte_prefer_min: int = 21,
    swing_dte_prefer_max: int = 45,
) -> list[StrategyCandidate]:
    """Filter liquid contracts, then build requested strategy types."""
    liquid = enrich_contracts(
        list(contracts),
        settings=liquidity_settings or LiquiditySettings(),
        include_rejected=False,
        sort_by_liquidity=False,
    )
    # Need delta for strike selection; each leg must clear a minimum liquidity bar.
    liquid = [
        c
        for c in liquid
        if c.delta is not None
        and (c.liquidity_score or 0) >= min_leg_liquidity_score
    ]

    candidates: list[StrategyCandidate] = []
    for strategy_type in strategy_types:
        builder = BUILDERS.get(strategy_type)
        if builder is None:
            continue
        kwargs: dict = {
            "underlying_symbol": underlying_symbol,
            "underlying_price": underlying_price,
            "slippage": slippage,
            "max_candidates": max_candidates_per_strategy,
        }
        if strategy_type in {"bull_put_credit", "bear_call_credit", "iron_condor"}:
            kwargs["min_credit_to_width"] = min_credit_to_width
        candidates.extend(builder(liquid, **kwargs))

    # Drop exact duplicate structures (same type, expiration, and leg set).
    deduped: list[StrategyCandidate] = []
    seen: set[tuple] = set()
    for cand in candidates:
        key = (
            cand.strategy_type,
            cand.expiration_date,
            frozenset(
                (leg.contract_type, leg.strike, leg.action) for leg in cand.legs
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cand)
    candidates = deduped

    def _sort_key(c: StrategyCandidate) -> tuple:
        sweet = _dte_in_swing_sweet_spot(
            c.dte, swing_dte_prefer_min, swing_dte_prefer_max
        )
        rr = (
            (c.credit_to_width or 0)
            if c.is_credit
            else (c.max_profit or 0) / max(c.max_loss or 1, 1e-6)
        )
        return (sweet, c.liquidity_score, rr)

    candidates.sort(key=_sort_key, reverse=True)
    return candidates
