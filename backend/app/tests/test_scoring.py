from datetime import date

from app.analytics.scoring import (
    alpha_score,
    apply_composite_score,
    grade_from_score,
    risk_penalty,
)
from app.schemas.strategy import OptionLeg, StrategyCandidate


def _candidate(**overrides) -> StrategyCandidate:
    base = dict(
        strategy_id="s1",
        underlying_symbol="SPY",
        underlying_price=550.0,
        strategy_type="bull_put_credit",
        expiration_date=date(2026, 8, 21),
        dte=40,
        legs=[
            OptionLeg(
                contract_symbol="S",
                action="sell",
                contract_type="put",
                strike=540,
                expiration_date=date(2026, 8, 21),
                price_used=1.5,
                delta=-0.25,
                gamma=0.01,
                theta=0.05,
                vega=0.10,
            ),
            OptionLeg(
                contract_symbol="L",
                action="buy",
                contract_type="put",
                strike=535,
                expiration_date=date(2026, 8, 21),
                price_used=0.8,
                delta=-0.15,
                gamma=0.008,
                theta=0.03,
                vega=0.08,
            ),
        ],
        legs_summary="S540P / B535P",
        net_debit_or_credit=0.7,
        is_credit=True,
        max_profit=0.7,
        max_loss=4.3,
        credit_to_width=0.14,
        liquidity_score=80.0,
        alpha=0.05,
        ev_physical=0.215,
        pop_physical=0.7,
        warnings=[],
        explanation="",
    )
    base.update(overrides)
    return StrategyCandidate(**base)


def test_alpha_score_examples():
    assert alpha_score(0.02) == 60.0
    assert alpha_score(0.05) == 75.0
    assert alpha_score(0.10) == 100.0


def test_grade_from_score():
    assert grade_from_score(92) == "A"
    assert grade_from_score(85) == "B"
    assert grade_from_score(72) == "C"
    assert grade_from_score(61) == "D"
    assert grade_from_score(40) == "F"


def test_high_ev_high_liquidity_ranks_above_poor():
    good = apply_composite_score(
        _candidate(alpha=0.08, liquidity_score=90, ev_physical=0.3),
        vol_score_short=80,
        vol_score_long=40,
        iv_rank=70,
        iv_history_count=100,
    )
    poor = apply_composite_score(
        _candidate(
            strategy_id="s2",
            alpha=-0.05,
            liquidity_score=20,
            ev_physical=-0.2,
            warnings=["No bid/ask in API data"],
        ),
        vol_score_short=30,
        vol_score_long=40,
        iv_rank=20,
        iv_history_count=5,
    )
    assert (good.final_score or 0) > (poor.final_score or 0)
    assert good.grade in {"A", "B", "C"}
    assert poor.grade in {"D", "F"}


def test_earnings_style_penalty_via_negative_ev_and_short_dte():
    cand = _candidate(dte=5, ev_physical=-0.1, alpha=-0.02)
    scored = apply_composite_score(
        cand,
        vol_score_short=70,
        vol_score_long=30,
        iv_history_count=50,
    )
    assert scored.final_score is not None
    assert any("Short DTE" in w or "Negative modeled EV" in w for w in scored.warnings)


def test_missing_iv_history_not_double_penalized():
  # Thin IV history is neutralized in iv_context_score; risk_penalty should not
  # stack a large duplicate hit on top.
  penalty, notes = risk_penalty(_candidate(), iv_history_count=0)
  assert penalty < 10
  assert not any("Limited IV history" in n for n in notes)


def test_explanation_uses_careful_language():
    scored = apply_composite_score(
        _candidate(alpha=0.06),
        vol_score_short=75,
        vol_score_long=40,
        iv_rank=65,
        iv_history_count=40,
    )
    text = scored.explanation.lower()
    assert "modeled" in text or "expectancy" in text
    assert "guaranteed" not in text
    assert "backtest" in text
    assert scored.score_breakdown
    assert scored.greek_score is not None
