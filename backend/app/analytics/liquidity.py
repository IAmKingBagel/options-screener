"""Liquidity scoring, moneyness, stale-quote checks, and contract warnings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.schemas.option import OptionContractSnapshot


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def compute_moneyness(underlying_price: Optional[float], strike: float) -> Optional[float]:
    """Spot/strike ratio. ~1.0 is at-the-money."""
    if underlying_price is None or underlying_price <= 0 or strike <= 0:
        return None
    return underlying_price / strike


def quote_age_minutes(
    quote_timestamp: Optional[datetime],
    as_of: Optional[datetime] = None,
) -> Optional[float]:
    if quote_timestamp is None:
        return None
    reference = as_of or datetime.now(timezone.utc)
    quote_ts = quote_timestamp
    if quote_ts.tzinfo is None:
        quote_ts = quote_ts.replace(tzinfo=timezone.utc)
    age_seconds = (reference - quote_ts).total_seconds()
    return max(age_seconds / 60.0, 0.0)


@dataclass(frozen=True)
class LiquiditySettings:
    min_open_interest: int = 100
    min_volume: int = 10
    max_spread_pct: float = 0.15
    max_spread_pct_warning: float = 0.25
    # Hard stale threshold for short-dated contracts (minutes).
    quote_stale_minutes_short_dte: float = 45.0
    # Warning-only threshold for swing contracts (minutes).
    quote_stale_minutes_swing_warning: float = 120.0
    short_dte_threshold: int = 7
    swing_dte_min: int = 14
    require_volume: bool = False


@dataclass
class LiquidityAssessment:
    liquidity_score: float
    moneyness: Optional[float]
    quote_age_minutes: Optional[float]
    passes_liquidity: bool
    warnings: list[str]


def _spread_score(spread_pct: Optional[float], max_spread_pct: float) -> float:
    if spread_pct is None:
        return 0.0
    return clamp(1.0 - spread_pct / max(max_spread_pct, 1e-6), 0.0, 1.0)


def _oi_score(open_interest: Optional[int]) -> float:
    if open_interest is None:
        return 0.0
    return clamp(math.log10(open_interest + 1) / 4.0, 0.0, 1.0)


def _volume_score(volume: Optional[int]) -> float:
    if volume is None:
        return 0.0
    return clamp(math.log10(volume + 1) / 4.0, 0.0, 1.0)


def liquidity_score(
    contract: OptionContractSnapshot,
    settings: LiquiditySettings,
) -> float:
    """
    Composite liquidity score 0–100.

    With live quotes: spread 50%, OI 30%, volume 20%.
    Without live quotes (Starter tier): OI 55%, volume 35%, neutral spread 10%.
    """
    if contract.has_live_quote:
        spread_component = _spread_score(contract.spread_pct, settings.max_spread_pct)
        weights = (0.50, 0.30, 0.20)
    else:
        spread_component = 0.5
        weights = (0.10, 0.55, 0.35)

    oi_component = _oi_score(contract.open_interest)
    volume_component = _volume_score(contract.volume)

    score = 100.0 * (
        weights[0] * spread_component
        + weights[1] * oi_component
        + weights[2] * volume_component
    )

    age = quote_age_minutes(contract.quote_timestamp)
    if age is not None and contract.dte < settings.swing_dte_min:
        if age > settings.quote_stale_minutes_short_dte:
            score *= 0.5

    return round(clamp(score, 0.0, 100.0), 1)


def passes_liquidity_filters(
    contract: OptionContractSnapshot,
    settings: LiquiditySettings,
    *,
    as_of: Optional[datetime] = None,
) -> bool:
    """Hard gate — contracts that fail should not rank as trade candidates."""
    # Combined demonstrated liquidity. Delayed Starter-tier data frequently
    # under-reports (or zeroes) open interest even for heavily traded near-ATM
    # strikes, so a rigid OI>=100 gate produces large numbers of false rejects.
    # Treat recent volume as a substitute: a contract is tradeable if its open
    # interest OR its recent volume (or the two combined) clear the OI floor.
    # The liquidity *score* still penalizes thin OI, so these rank lower.
    demonstrated_liquidity = (contract.open_interest or 0) + (contract.volume or 0)
    if demonstrated_liquidity < settings.min_open_interest:
        return False

    if contract.has_live_quote:
        if contract.bid is None or contract.bid <= 0:
            return False
        if contract.ask is None or contract.ask <= contract.bid:
            return False
        if contract.mid is None or contract.mid <= 0:
            return False

        spread_pct = contract.spread_pct
        if spread_pct is None:
            return False

        max_allowed = settings.max_spread_pct
        if _is_far_otm(contract):
            max_allowed = settings.max_spread_pct_warning

        if spread_pct > max_allowed:
            return False
    else:
        # Starter tier often omits last_quote — screen on OI + day-bar activity.
        if contract.mid is None or contract.mid <= 0:
            return False
        if settings.require_volume:
            if contract.volume is None or contract.volume < settings.min_volume:
                return False

    if settings.require_volume and contract.has_live_quote:
        if contract.volume is None or contract.volume < settings.min_volume:
            return False

    age = quote_age_minutes(contract.quote_timestamp, as_of=as_of)
    if age is not None and contract.dte < settings.short_dte_threshold:
        if age > settings.quote_stale_minutes_short_dte:
            return False

    return True


def _is_far_otm(contract: OptionContractSnapshot) -> bool:
    moneyness = compute_moneyness(contract.underlying_price, contract.strike)
    if moneyness is None:
        return False
    if contract.contract_type == "call":
        return moneyness < 0.90
    return moneyness > 1.10


def contract_warnings(
    contract: OptionContractSnapshot,
    settings: LiquiditySettings,
    *,
    as_of: Optional[datetime] = None,
) -> list[str]:
    """Non-fatal warnings for contracts that may still be shown for research."""
    warnings: list[str] = []

    if not contract.has_live_quote:
        warnings.append("No bid/ask in API data — using day bar for screening")

    if contract.bid is None or contract.bid <= 0:
        if contract.has_live_quote:
            warnings.append("No bid")
    elif contract.ask is not None and contract.ask <= contract.bid:
        warnings.append("Invalid bid/ask")

    if contract.open_interest is not None and contract.open_interest < settings.min_open_interest:
        warnings.append(f"Low open interest ({contract.open_interest})")

    if contract.volume is not None and contract.volume < settings.min_volume:
        warnings.append(f"Low volume ({contract.volume})")

    if contract.spread_pct is not None:
        if contract.spread_pct > settings.max_spread_pct_warning:
            warnings.append(f"Very wide spread ({contract.spread_pct:.1%})")
        elif contract.spread_pct > settings.max_spread_pct:
            warnings.append(f"Wide spread ({contract.spread_pct:.1%})")

    age = quote_age_minutes(contract.quote_timestamp, as_of=as_of)
    if age is not None:
        if contract.dte < settings.short_dte_threshold and age > settings.quote_stale_minutes_short_dte:
            warnings.append(f"Stale quote ({age:.0f} min old, short DTE)")
        elif contract.dte >= settings.swing_dte_min and age > settings.quote_stale_minutes_swing_warning:
            warnings.append(f"Quote may be stale ({age:.0f} min old)")

    if contract.dte < settings.short_dte_threshold:
        warnings.append("Short DTE — high gamma risk")

    if contract.implied_volatility is None:
        warnings.append("Missing implied volatility")

    if contract.delta is None:
        warnings.append("Missing delta")

    if _is_far_otm(contract):
        warnings.append("Far OTM — lottery-style contract")

    return warnings


def assess_contract(
    contract: OptionContractSnapshot,
    settings: Optional[LiquiditySettings] = None,
    *,
    as_of: Optional[datetime] = None,
) -> LiquidityAssessment:
    settings = settings or LiquiditySettings()
    moneyness = compute_moneyness(contract.underlying_price, contract.strike)
    age = quote_age_minutes(contract.quote_timestamp, as_of=as_of)
    warnings = contract_warnings(contract, settings, as_of=as_of)
    passes = passes_liquidity_filters(contract, settings, as_of=as_of)
    score = liquidity_score(contract, settings)

    return LiquidityAssessment(
        liquidity_score=score,
        moneyness=moneyness,
        quote_age_minutes=age,
        passes_liquidity=passes,
        warnings=warnings,
    )


def enrich_contract(
    contract: OptionContractSnapshot,
    settings: Optional[LiquiditySettings] = None,
    *,
    as_of: Optional[datetime] = None,
) -> OptionContractSnapshot:
    assessment = assess_contract(contract, settings=settings, as_of=as_of)
    return contract.model_copy(
        update={
            "moneyness": assessment.moneyness,
            "liquidity_score": assessment.liquidity_score,
            "quote_age_minutes": assessment.quote_age_minutes,
            "passes_liquidity": assessment.passes_liquidity,
            "contract_warnings": assessment.warnings,
        }
    )


def enrich_contracts(
    contracts: list[OptionContractSnapshot],
    settings: Optional[LiquiditySettings] = None,
    *,
    as_of: Optional[datetime] = None,
    include_rejected: bool = False,
    sort_by_liquidity: bool = True,
) -> list[OptionContractSnapshot]:
    enriched = [
        enrich_contract(contract, settings=settings, as_of=as_of) for contract in contracts
    ]

    if not include_rejected:
        enriched = [c for c in enriched if c.passes_liquidity]

    if sort_by_liquidity:
        enriched.sort(
            key=lambda c: (c.liquidity_score or 0.0, c.open_interest or 0),
            reverse=True,
        )

    return enriched
