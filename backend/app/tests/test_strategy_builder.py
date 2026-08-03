from datetime import date

from app.analytics.strategy_builder import (
    build_bear_call_spreads,
    build_bull_put_spreads,
    build_iron_condors,
    build_strategies,
)
from app.schemas.option import OptionContractSnapshot


def _c(**overrides) -> OptionContractSnapshot:
    base = dict(
        symbol="X",
        underlying_symbol="SPY",
        underlying_price=550.0,
        contract_type="put",
        expiration_date=date(2026, 8, 21),
        strike=540.0,
        dte=40,
        bid=2.0,
        ask=2.2,
        mid=2.1,
        open_interest=500,
        volume=50,
        implied_volatility=0.2,
        delta=-0.25,
        has_live_quote=True,
        liquidity_score=70.0,
        passes_liquidity=True,
    )
    base.update(overrides)
    return OptionContractSnapshot(**base)


def _liquid_chain() -> list[OptionContractSnapshot]:
    # Puts for bull put / iron condor
    puts = [
        _c(symbol="P530", strike=530, delta=-0.15, mid=1.0, bid=0.9, ask=1.1),
        _c(symbol="P535", strike=535, delta=-0.20, mid=1.5, bid=1.4, ask=1.6),
        _c(symbol="P540", strike=540, delta=-0.25, mid=2.1, bid=2.0, ask=2.2),
        _c(symbol="P545", strike=545, delta=-0.32, mid=3.0, bid=2.9, ask=3.1),
        _c(symbol="P550", strike=550, delta=-0.50, mid=5.0, bid=4.9, ask=5.1),
        _c(symbol="P555", strike=555, delta=-0.60, mid=7.0, bid=6.9, ask=7.1),
    ]
    # Calls for bear call / iron condor / bull call
    calls = [
        _c(
            symbol="C550",
            contract_type="call",
            strike=550,
            delta=0.50,
            mid=5.0,
            bid=4.9,
            ask=5.1,
        ),
        _c(
            symbol="C555",
            contract_type="call",
            strike=555,
            delta=0.40,
            mid=3.5,
            bid=3.4,
            ask=3.6,
        ),
        _c(
            symbol="C560",
            contract_type="call",
            strike=560,
            delta=0.25,
            mid=2.1,
            bid=2.0,
            ask=2.2,
        ),
        _c(
            symbol="C565",
            contract_type="call",
            strike=565,
            delta=0.20,
            mid=1.5,
            bid=1.4,
            ask=1.6,
        ),
        _c(
            symbol="C570",
            contract_type="call",
            strike=570,
            delta=0.15,
            mid=1.0,
            bid=0.9,
            ask=1.1,
        ),
        _c(
            symbol="C575",
            contract_type="call",
            strike=575,
            delta=0.10,
            mid=0.6,
            bid=0.5,
            ask=0.7,
        ),
    ]
    return puts + calls


def test_bull_put_legs_same_expiration_and_order():
    candidates = build_bull_put_spreads(
        _liquid_chain(),
        underlying_symbol="SPY",
        underlying_price=550.0,
        min_credit_to_width=0.05,
    )
    assert candidates
    for cand in candidates:
        assert cand.strategy_type == "bull_put_credit"
        assert cand.is_credit
        assert len(cand.legs) == 2
        sell, buy = cand.legs
        assert sell.action == "sell"
        assert buy.action == "buy"
        assert sell.expiration_date == buy.expiration_date
        assert sell.strike > buy.strike
        assert cand.max_profit is not None and cand.max_profit > 0
        assert cand.max_loss is not None and cand.max_loss > 0


def test_bear_call_leg_ordering():
    candidates = build_bear_call_spreads(
        _liquid_chain(),
        underlying_symbol="SPY",
        underlying_price=550.0,
        min_credit_to_width=0.05,
    )
    assert candidates
    sell, buy = candidates[0].legs
    assert sell.action == "sell" and buy.action == "buy"
    assert buy.strike > sell.strike


def test_iron_condor_has_four_legs():
    candidates = build_iron_condors(
        _liquid_chain(),
        underlying_symbol="SPY",
        underlying_price=550.0,
        min_credit_to_width=0.05,
    )
    assert candidates
    cand = candidates[0]
    assert len(cand.legs) == 4
    assert cand.is_credit
    actions = [leg.action for leg in cand.legs]
    assert actions.count("sell") == 2
    assert actions.count("buy") == 2


def test_build_strategies_skips_illiquid_legs():
    chain = _liquid_chain()
    # Mark far OTM put as illiquid / no price
    bad = _c(
        symbol="BAD",
        strike=400,
        delta=-0.25,
        mid=None,
        bid=None,
        ask=None,
        open_interest=5,
        has_live_quote=False,
        passes_liquidity=False,
        liquidity_score=5,
    )
    candidates = build_strategies(
        chain + [bad],
        underlying_symbol="SPY",
        underlying_price=550.0,
        strategy_types=["bull_put_credit"],
    )
    symbols = {leg.contract_symbol for c in candidates for leg in c.legs}
    assert "BAD" not in symbols
