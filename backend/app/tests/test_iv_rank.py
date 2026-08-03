from datetime import date

import pytest

from app.analytics.iv_rank import (
    compute_iv_percentile,
    compute_iv_rank,
    estimate_atm_iv,
    estimate_iv30_from_chain,
    history_status,
    interpolate_iv30,
)
from app.schemas.option import OptionContractSnapshot


def _contract(**overrides) -> OptionContractSnapshot:
    base = dict(
        symbol="O:SPY260821C00550000",
        underlying_symbol="SPY",
        underlying_price=550.0,
        contract_type="call",
        expiration_date=date(2026, 8, 21),
        strike=550.0,
        dte=30,
        bid=2.0,
        ask=2.1,
        mid=2.05,
        open_interest=500,
        implied_volatility=0.18,
        delta=0.50,
        has_live_quote=True,
    )
    base.update(overrides)
    return OptionContractSnapshot(**base)


def test_iv_rank_at_min_is_zero():
    assert compute_iv_rank(0.10, [0.10, 0.20, 0.30]) == pytest.approx(0.0)


def test_iv_rank_at_max_is_100():
    assert compute_iv_rank(0.30, [0.10, 0.20, 0.30]) == pytest.approx(100.0)


def test_iv_percentile():
    # 2 of 4 values strictly below 0.20
    assert compute_iv_percentile(0.20, [0.10, 0.15, 0.20, 0.25]) == pytest.approx(50.0)


def test_iv_rank_empty_history():
    assert compute_iv_rank(0.20, []) is None


def test_interpolate_iv30():
    points = [(20, 0.20), (40, 0.16)]
    iv30 = interpolate_iv30(points)
    assert iv30 == pytest.approx(0.18)


def test_estimate_atm_iv_prefers_delta_near_50():
    contracts = [
        _contract(strike=540, delta=0.60, implied_volatility=0.22),
        _contract(strike=550, delta=0.50, implied_volatility=0.18),
        _contract(strike=560, delta=0.40, implied_volatility=0.21),
        _contract(
            contract_type="put",
            strike=550,
            delta=-0.50,
            implied_volatility=0.19,
            symbol="PUT",
        ),
    ]
    atm = estimate_atm_iv(contracts, underlying_price=550.0)
    assert atm == pytest.approx((0.18 + 0.19) / 2)


def test_estimate_iv30_from_chain():
    contracts = [
        _contract(dte=20, implied_volatility=0.22, delta=0.50),
        _contract(
            dte=20,
            contract_type="put",
            delta=-0.50,
            implied_volatility=0.22,
            symbol="P20",
        ),
        _contract(dte=40, implied_volatility=0.16, delta=0.50, symbol="C40"),
        _contract(
            dte=40,
            contract_type="put",
            delta=-0.50,
            implied_volatility=0.16,
            symbol="P40",
        ),
    ]
    iv30, points, warnings = estimate_iv30_from_chain(
        contracts, underlying_price=550.0
    )
    assert iv30 == pytest.approx(0.19)
    assert len(points) == 2
    assert warnings == []


def test_history_status_labels():
    assert history_status(0) == "no_history"
    assert history_status(30) == "limited_30d"
    assert history_status(252) == "full_52w"
