from datetime import date, datetime, timezone

import pytest

from app.analytics.liquidity import (
    LiquiditySettings,
    assess_contract,
    compute_moneyness,
    enrich_contracts,
    liquidity_score,
    passes_liquidity_filters,
)
from app.schemas.option import OptionContractSnapshot


def _contract(**overrides) -> OptionContractSnapshot:
    base = dict(
        symbol="O:SPY260821C00550000",
        underlying_symbol="SPY",
        underlying_price=547.25,
        contract_type="call",
        expiration_date=date(2026, 8, 21),
        strike=550.0,
        dte=50,
        bid=2.10,
        ask=2.20,
        mid=2.15,
        spread_abs=0.10,
        spread_pct=0.10 / 2.15,
        volume=500,
        open_interest=1500,
        implied_volatility=0.18,
        delta=0.48,
        has_live_quote=True,
    )
    base.update(overrides)
    return OptionContractSnapshot(**base)


def test_compute_moneyness():
    assert compute_moneyness(547.25, 550.0) == pytest.approx(0.995)


def test_reject_no_bid_without_live_quote_uses_day_bar():
    contract = _contract(bid=None, ask=None, mid=2.15, last=2.15, has_live_quote=False)
    assert passes_liquidity_filters(contract, LiquiditySettings()) is True


def test_reject_no_bid_with_live_quote():
    contract = _contract(bid=0, ask=0.10, mid=None, spread_pct=None, has_live_quote=True)
    assert passes_liquidity_filters(contract, LiquiditySettings()) is False
    assessment = assess_contract(contract)
    assert assessment.passes_liquidity is False
    assert any("No bid" in warning for warning in assessment.warnings)


def test_reject_invalid_spread():
    contract = _contract(bid=2.20, ask=2.10, mid=2.15, spread_abs=-0.10, has_live_quote=True)
    assert passes_liquidity_filters(contract, LiquiditySettings()) is False


def test_penalize_wide_spread_score():
    tight = _contract(spread_pct=0.03)
    wide = _contract(spread_pct=0.20, bid=1.0, ask=1.43, mid=1.215)
    assert liquidity_score(tight, LiquiditySettings()) > liquidity_score(
        wide, LiquiditySettings()
    )


def test_reject_wide_spread_beyond_gate():
    contract = _contract(spread_pct=0.30, bid=1.0, ask=1.60, mid=1.30)
    assert passes_liquidity_filters(contract, LiquiditySettings()) is False


def test_high_oi_scores_better_than_low_oi():
    liquid = _contract(open_interest=5000, volume=800)
    illiquid = _contract(open_interest=10, volume=2)
    assert liquidity_score(liquid, LiquiditySettings()) > liquidity_score(
        illiquid, LiquiditySettings()
    )


def test_enrich_contracts_filters_rejected_by_default():
    good = _contract(symbol="GOOD")
    bad = _contract(
        symbol="BAD",
        bid=None,
        ask=None,
        mid=None,
        spread_pct=None,
        open_interest=5,
        has_live_quote=False,
    )
    visible = enrich_contracts([good, bad], include_rejected=False)
    assert len(visible) == 1
    assert visible[0].symbol == "GOOD"
    assert visible[0].liquidity_score is not None


def test_enrich_contracts_sorts_by_liquidity_desc():
    low = _contract(symbol="LOW", open_interest=100, volume=10)
    high = _contract(symbol="HIGH", open_interest=10000, volume=5000)
    visible = enrich_contracts([low, high], include_rejected=False)
    assert visible[0].symbol == "HIGH"


def test_swing_dte_stale_quote_warns_not_auto_reject():
    stale_ts = datetime.now(timezone.utc).replace(microsecond=0)
    contract = _contract(
        dte=30,
        quote_timestamp=stale_ts.replace(year=stale_ts.year - 1),
    )
    assessment = assess_contract(contract)
    assert assessment.passes_liquidity is True
    assert any("stale" in w.lower() for w in assessment.warnings)
