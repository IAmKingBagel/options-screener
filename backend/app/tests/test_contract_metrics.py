from datetime import date

import pytest

from app.analytics.contract_metrics import compute_dte, compute_mid, compute_spread


def test_compute_mid_from_bid_ask():
    assert compute_mid(2.10, 2.20) == pytest.approx(2.15)


def test_compute_mid_rejects_invalid_quotes():
    assert compute_mid(None, 2.20) is None
    assert compute_mid(2.20, 2.10) is None
    assert compute_mid(0, 2.10) is None


def test_compute_spread():
    spread_abs, spread_pct = compute_spread(2.10, 2.20, mid=2.15)
    assert spread_abs == pytest.approx(0.10)
    assert spread_pct == pytest.approx(0.10 / 2.15, rel=1e-6)


def test_compute_dte_future_expiration():
    as_of = date(2026, 7, 2)
    expiration = date(2026, 8, 21)
    assert compute_dte(expiration, as_of=as_of) == 50
