import math

import pytest

from app.analytics.realized_vol import (
    log_returns,
    realized_vol,
    variance_risk_premium,
    volatility_scores,
    weighted_forecast_rv,
)


def test_constant_price_gives_zero_vol():
    closes = [100.0] * 30
    assert realized_vol(closes, 10) == pytest.approx(0.0)


def test_log_returns_known_values():
    closes = [100.0, 110.0, 121.0]
    returns = log_returns(closes)
    assert returns[0] == pytest.approx(math.log(1.1))
    assert returns[1] == pytest.approx(math.log(1.1))


def test_realized_vol_known_series():
    # Alternating +1% / -1% log-ish moves via multiplicative factors.
    closes = [100.0]
    for _ in range(20):
        closes.append(closes[-1] * 1.01)
        closes.append(closes[-1] / 1.01)
    rv = realized_vol(closes, 20)
    assert rv is not None
    assert rv > 0


def test_weighted_forecast_rv():
    forecast = weighted_forecast_rv(0.20, 0.18, 0.16)
    assert forecast == pytest.approx(0.50 * 0.20 + 0.30 * 0.18 + 0.20 * 0.16)


def test_weighted_forecast_partial():
    assert weighted_forecast_rv(0.20, None, None) == pytest.approx(0.20)


def test_variance_risk_premium():
    vrp = variance_risk_premium(0.25, 0.20)
    assert vrp == pytest.approx(0.25**2 - 0.20**2)


def test_volatility_scores_positive_vrp_favors_short():
    _, short_score, long_score = volatility_scores(0.02)
    assert short_score is not None and long_score is not None
    assert short_score > long_score
