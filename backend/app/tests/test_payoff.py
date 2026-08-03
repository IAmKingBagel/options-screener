from app.analytics.payoff import (
    breakevens_iron_condor,
    breakevens_vertical,
    max_profit_loss_for_iron_condor,
    max_profit_loss_for_vertical,
    option_leg_payoff,
)


def test_bull_put_spread_max_profit_loss():
    # Credit 1.0 on $5 wide spread
    max_profit, max_loss = max_profit_loss_for_vertical(
        is_credit=True, width=5.0, net_premium=1.0
    )
    assert max_profit == 1.0
    assert max_loss == 4.0


def test_bear_call_spread_max_profit_loss():
    max_profit, max_loss = max_profit_loss_for_vertical(
        is_credit=True, width=5.0, net_premium=1.2
    )
    assert max_profit == 1.2
    assert max_loss == 3.8


def test_bull_call_debit_max_profit_loss():
    max_profit, max_loss = max_profit_loss_for_vertical(
        is_credit=False, width=5.0, net_premium=1.5
    )
    assert max_profit == 3.5
    assert max_loss == 1.5


def test_iron_condor_payoff_bounds():
    max_profit, max_loss = max_profit_loss_for_iron_condor(
        put_width=5.0, call_width=5.0, net_credit=1.0
    )
    assert max_profit == 1.0
    assert max_loss == 4.0


def test_option_leg_payoff_long_call():
    # Buy call strike 100 for 2, terminal 110 -> intrinsic 10, pnl 8
    assert option_leg_payoff(
        contract_type="call",
        strike=100,
        action="buy",
        quantity=1,
        entry_price=2.0,
        terminal_price=110,
    ) == 8.0


def test_breakevens_bull_put_credit():
    be = breakevens_vertical(
        strategy_type="bull_put_credit",
        short_strike=100,
        long_strike=95,
        net_premium=1.0,
        is_credit=True,
    )
    assert be == [99.0]


def test_breakevens_iron_condor():
    be = breakevens_iron_condor(short_put=95, short_call=105, net_credit=1.0)
    assert be == [94.0, 106.0]
