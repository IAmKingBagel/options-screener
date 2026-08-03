from datetime import date, datetime, timezone

from app.db.models import TrackedCandidate
from app.schemas.strategy import OptionLeg, StrategyCandidate
from app.services.tracking_service import (
    TrackingService,
    _intrinsic_value,
    _settlement_mark_net,
)


def _candidate() -> StrategyCandidate:
    return StrategyCandidate(
        strategy_id="track-test-001",
        underlying_symbol="SPY",
        underlying_price=550.0,
        strategy_type="bull_put_credit",
        expiration_date=date(2026, 8, 21),
        dte=40,
        legs=[
            OptionLeg(
                contract_symbol="S540P",
                action="sell",
                contract_type="put",
                strike=540,
                expiration_date=date(2026, 8, 21),
                price_used=1.5,
            ),
            OptionLeg(
                contract_symbol="L535P",
                action="buy",
                contract_type="put",
                strike=535,
                expiration_date=date(2026, 8, 21),
                price_used=0.8,
            ),
        ],
        legs_summary="S540P / B535P",
        net_debit_or_credit=0.7,
        is_credit=True,
        max_profit=0.7,
        max_loss=4.3,
        alpha=0.05,
        final_score=72.0,
        grade="C",
        ev_physical=0.2,
        pop_physical=0.65,
        liquidity_score=80.0,
        score_breakdown={"final_score": 72.0},
        explanation="Test candidate",
    )


def test_track_and_list(db_session):
    service = TrackingService()
    saved = service.track(db_session, _candidate())
    assert saved.id > 0
    assert saved.status == "open"
    assert saved.entry_net == 0.7
    assert saved.latest_pnl == 0.0
    assert len(saved.marks) == 1

    listed = service.list_tracked(db_session)
    assert listed.summary["open_count"] == 1
    assert listed.open[0].strategy_id == "track-test-001"
    assert listed.open[0].score_vs_outcome is not None


def test_track_is_idempotent_for_open(db_session):
    service = TrackingService()
    first = service.track(db_session, _candidate())
    second = service.track(db_session, _candidate())
    assert first.id == second.id
    listed = service.list_tracked(db_session)
    assert listed.summary["open_count"] == 1


def test_close_tracked(db_session):
    service = TrackingService()
    saved = service.track(db_session, _candidate())

    # Avoid live API refresh on close by marking closed path with a stub.
    class StubService(TrackingService):
        def refresh_one(self, db, tracked_id):
            return self.get_one(db, tracked_id)

    closed = StubService().close(db_session, saved.id, reason="manual")
    assert closed is not None
    assert closed.status == "closed"
    assert closed.close_reason == "manual"

    listed = service.list_tracked(db_session)
    assert listed.summary["open_count"] == 0
    assert listed.summary["closed_count"] == 1


def test_pnl_credit_logic(db_session):
    service = TrackingService()
    saved = service.track(db_session, _candidate())
    row = service.get_one(db_session, saved.id)
    assert row is not None
    # Entry mark uses entry_net as mark_net for credit => pnl 0
    assert row.latest_pnl == 0.0


def test_intrinsic_value():
    assert _intrinsic_value("call", 100.0, 110.0) == 10.0
    assert _intrinsic_value("call", 100.0, 90.0) == 0.0
    assert _intrinsic_value("put", 100.0, 90.0) == 10.0
    assert _intrinsic_value("put", 100.0, 110.0) == 0.0


def test_settlement_credit_spread_expires_worthless():
    # Bull put credit: sell 540 put / buy 535 put, entry credit 0.7, max loss 4.3.
    legs = _candidate().legs
    # Underlying settles above both strikes -> both puts worthless.
    mark_net = _settlement_mark_net(legs, underlying_price=550.0, is_credit=True)
    # cost to close is 0; P/L = entry_net - mark_net = 0.7 - 0 = full credit kept.
    assert mark_net == 0.0


def test_settlement_credit_spread_max_loss():
    legs = _candidate().legs
    # Underlying below both strikes -> spread at full width (5 wide).
    mark_net = _settlement_mark_net(legs, underlying_price=530.0, is_credit=True)
    # buy back 540 put (10) minus sell 535 put (5) = 5 cost to close.
    assert mark_net == 5.0  # P/L = 0.7 - 5 = -4.3 == -max_loss


def test_failed_mark_preserves_last_pnl(db_session):
    service = TrackingService()
    saved = service.track(db_session, _candidate())
    row = db_session.get(TrackedCandidate, saved.id)
    assert row.latest_pnl == 0.0

    # A data gap yields no mark; last known P/L must be preserved, not wiped.
    service._record_mark(
        db_session, row, mark_net=None, underlying_price=None, notes="data gap"
    )
    refreshed = service.get_one(db_session, saved.id)
    assert refreshed.latest_pnl == 0.0
    # The failed attempt is still recorded as a mark row for audit.
    assert len(refreshed.marks) == 2
    assert refreshed.marks[-1].pnl is None
