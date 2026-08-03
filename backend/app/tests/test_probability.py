from datetime import date

import pytest

from app.analytics.ev_engine import score_candidate_ev
from app.analytics.payoff import strategy_payoff_grid
from app.analytics.probability import (
    alpha_from_ev,
    expected_value_from_grid,
    lognormal_probabilities,
    probability_profit,
    terminal_price_grid,
)
from app.schemas.strategy import OptionLeg, StrategyCandidate


def test_probability_weights_sum_to_one():
    prices = terminal_price_grid(100.0, 0.20, 30, n_points=500)
    probs = lognormal_probabilities(
        prices, spot=100.0, annual_vol=0.20, dte=30, drift=0.0
    )
    assert sum(probs) == pytest.approx(1.0, abs=1e-6)


def test_pop_for_always_positive_payoff():
    payoffs = [1.0, 2.0, 3.0]
    probs = [0.2, 0.3, 0.5]
    assert probability_profit(payoffs, probs) == pytest.approx(1.0)


def test_pop_for_mixed_payoff():
    payoffs = [-1.0, 1.0, 2.0]
    probs = [0.5, 0.25, 0.25]
    assert probability_profit(payoffs, probs) == pytest.approx(0.5)


def test_expected_value_from_grid():
    payoffs = [1.0, -1.0]
    probs = [0.6, 0.4]
    assert expected_value_from_grid(payoffs, probs) == pytest.approx(0.2)


def test_alpha_from_ev():
    assert alpha_from_ev(0.2, 4.0) == pytest.approx(0.05)


def test_strategy_payoff_grid_bull_put():
    legs = [
        OptionLeg(
            contract_symbol="S",
            action="sell",
            contract_type="put",
            strike=100,
            expiration_date=date(2026, 8, 21),
            price_used=1.0,
        ),
        OptionLeg(
            contract_symbol="L",
            action="buy",
            contract_type="put",
            strike=95,
            expiration_date=date(2026, 8, 21),
            price_used=0.0,
        ),
    ]
    # Credit 1.0, width 5. At 100+: max profit 1. At 95-: max loss 4.
    payoffs = strategy_payoff_grid(legs, [90.0, 100.0, 110.0], commission_per_contract=0.0)
    assert payoffs[0] == pytest.approx(-4.0)
    assert payoffs[1] == pytest.approx(1.0)
    assert payoffs[2] == pytest.approx(1.0)


def test_score_candidate_ev_sets_alpha():
    candidate = StrategyCandidate(
        strategy_id="t1",
        underlying_symbol="SPY",
        underlying_price=100.0,
        strategy_type="bull_put_credit",
        expiration_date=date(2026, 8, 21),
        dte=30,
        legs=[
            OptionLeg(
                contract_symbol="S",
                action="sell",
                contract_type="put",
                strike=95,
                expiration_date=date(2026, 8, 21),
                price_used=1.0,
                implied_volatility=0.20,
            ),
            OptionLeg(
                contract_symbol="L",
                action="buy",
                contract_type="put",
                strike=90,
                expiration_date=date(2026, 8, 21),
                price_used=0.3,
                implied_volatility=0.22,
            ),
        ],
        legs_summary="S95P / B90P",
        net_debit_or_credit=0.7,
        is_credit=True,
        max_profit=0.7,
        max_loss=4.3,
    )
    scored = score_candidate_ev(
        candidate,
        forecast_rv=0.15,
        iv30=0.20,
        commission_per_contract=0.0,
        n_points=400,
    )
    assert scored.ev_physical is not None
    assert scored.pop_physical is not None
    assert scored.alpha is not None
    assert scored.ev_risk_neutral is not None
    assert scored.pop_risk_neutral is not None
    assert 0.0 <= scored.pop_physical <= 1.0
    assert len(scored.payoff_curve) > 0
