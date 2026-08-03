"""Save candidates and track mark-to-market outcomes over time."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.strategy_builder import _leg_price
from app.data.massive_client import MassiveAPIError
from app.db.models import CandidateMark, TrackedCandidate
from app.schemas.option import OptionContractSnapshot
from app.schemas.strategy import OptionLeg, StrategyCandidate
from app.schemas.tracking import (
    CandidateMarkOut,
    TrackedCandidateOut,
    TrackedListResponse,
)
from app.services.chain_service import ChainService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _legs_to_json(legs: list[OptionLeg]) -> str:
    return json.dumps([leg.model_dump(mode="json") for leg in legs])


def _legs_from_json(payload: str) -> list[OptionLeg]:
    return [OptionLeg.model_validate(item) for item in json.loads(payload)]


def _intrinsic_value(contract_type: str, strike: float, underlying_price: float) -> float:
    if contract_type == "call":
        return max(underlying_price - strike, 0.0)
    return max(strike - underlying_price, 0.0)


def _settlement_mark_net(
    legs: list[OptionLeg],
    underlying_price: float,
    is_credit: bool,
) -> float:
    """Mark_net at expiration from intrinsic value, in the same convention as
    the live mark: for credits it's the cost to close, for debits the exit
    proceeds."""
    debit_parts = 0.0
    credit_parts = 0.0
    for leg in legs:
        intrinsic = _intrinsic_value(leg.contract_type, leg.strike, underlying_price)
        close_action = "buy" if leg.action == "sell" else "sell"
        if close_action == "buy":
            debit_parts += intrinsic * leg.quantity
        else:
            credit_parts += intrinsic * leg.quantity
    cost_to_close = debit_parts - credit_parts
    return cost_to_close if is_credit else -cost_to_close


def _score_vs_outcome(row: TrackedCandidate) -> Optional[str]:
    if row.latest_pnl is None or row.entry_final_score is None:
        return None
    high_score = row.entry_final_score >= 70
    positive = row.latest_pnl > 0
    if high_score and positive:
        return "High score, positive P/L so far"
    if high_score and not positive:
        return "High score, negative P/L so far — model may be wrong"
    if not high_score and positive:
        return "Lower score, positive P/L so far"
    return "Lower score, negative P/L so far"


def _to_out(row: TrackedCandidate, include_marks: bool = True) -> TrackedCandidateOut:
    breakdown = {}
    if row.score_breakdown_json:
        breakdown = json.loads(row.score_breakdown_json)
    marks: list[CandidateMarkOut] = []
    if include_marks:
        for mark in sorted(row.marks, key=lambda m: m.marked_at):
            marks.append(
                CandidateMarkOut(
                    id=mark.id,
                    marked_at=mark.marked_at,
                    days_since_entry=mark.days_since_entry,
                    underlying_price=mark.underlying_price,
                    mark_net=mark.mark_net,
                    pnl=mark.pnl,
                    pnl_pct_of_max_profit=mark.pnl_pct_of_max_profit,
                    notes=mark.notes,
                )
            )
    return TrackedCandidateOut(
        id=row.id,
        strategy_id=row.strategy_id,
        underlying_symbol=row.underlying_symbol,
        strategy_type=row.strategy_type,
        expiration_date=row.expiration_date,
        dte_at_entry=row.dte_at_entry,
        legs=_legs_from_json(row.legs_json),
        legs_summary=row.legs_summary,
        entry_net=row.entry_net,
        is_credit=row.is_credit,
        max_profit=row.max_profit,
        max_loss=row.max_loss,
        entry_underlying_price=row.entry_underlying_price,
        entry_alpha=row.entry_alpha,
        entry_final_score=row.entry_final_score,
        entry_grade=row.entry_grade,
        entry_ev_physical=row.entry_ev_physical,
        entry_pop_physical=row.entry_pop_physical,
        entry_liquidity_score=row.entry_liquidity_score,
        score_breakdown=breakdown,
        explanation=row.explanation,
        status=row.status,
        tracked_at=row.tracked_at,
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        latest_pnl=row.latest_pnl,
        latest_mark_net=row.latest_mark_net,
        latest_underlying_price=row.latest_underlying_price,
        latest_marked_at=row.latest_marked_at,
        pnl_1d=row.pnl_1d,
        pnl_3d=row.pnl_3d,
        pnl_7d=row.pnl_7d,
        pnl_14d=row.pnl_14d,
        hit_50pct_profit=row.hit_50pct_profit,
        hit_max_loss=row.hit_max_loss,
        marks=marks,
        score_vs_outcome=_score_vs_outcome(row),
    )


class TrackingService:
    def __init__(self, chain_service: Optional[ChainService] = None):
        self.chain_service = chain_service or ChainService()

    def track(self, db: Session, candidate: StrategyCandidate) -> TrackedCandidateOut:
        existing = db.scalar(
            select(TrackedCandidate).where(
                TrackedCandidate.strategy_id == candidate.strategy_id,
                TrackedCandidate.status == "open",
            )
        )
        if existing is not None:
            return _to_out(existing)

        now = _now()
        row = TrackedCandidate(
            strategy_id=candidate.strategy_id,
            underlying_symbol=candidate.underlying_symbol,
            strategy_type=candidate.strategy_type,
            expiration_date=candidate.expiration_date,
            dte_at_entry=candidate.dte,
            legs_json=_legs_to_json(candidate.legs),
            legs_summary=candidate.legs_summary,
            entry_net=candidate.net_debit_or_credit,
            is_credit=candidate.is_credit,
            max_profit=candidate.max_profit,
            max_loss=candidate.max_loss,
            entry_underlying_price=candidate.underlying_price,
            entry_alpha=candidate.alpha,
            entry_final_score=candidate.final_score,
            entry_grade=candidate.grade,
            entry_ev_physical=candidate.ev_physical,
            entry_pop_physical=candidate.pop_physical,
            entry_liquidity_score=candidate.liquidity_score,
            score_breakdown_json=json.dumps(candidate.score_breakdown or {}),
            explanation=candidate.explanation,
            status="open",
            tracked_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Initial mark at entry (P/L ≈ 0 aside from model noise).
        self._record_mark(
            db,
            row,
            mark_net=candidate.net_debit_or_credit,
            underlying_price=candidate.underlying_price,
            notes="Entry mark",
        )
        db.refresh(row)
        return _to_out(row)

    def list_tracked(self, db: Session) -> TrackedListResponse:
        rows = list(
            db.scalars(
                select(TrackedCandidate).order_by(TrackedCandidate.tracked_at.desc())
            )
        )
        open_rows = [_to_out(r) for r in rows if r.status == "open"]
        closed_rows = [_to_out(r) for r in rows if r.status != "open"]

        closed_pnls = [r.latest_pnl for r in rows if r.status != "open" and r.latest_pnl is not None]
        summary = {
            "open_count": len(open_rows),
            "closed_count": len(closed_rows),
            "closed_avg_pnl": (
                sum(closed_pnls) / len(closed_pnls) if closed_pnls else None
            ),
            "closed_win_rate": (
                sum(1 for p in closed_pnls if p > 0) / len(closed_pnls)
                if closed_pnls
                else None
            ),
        }
        return TrackedListResponse(open=open_rows, closed=closed_rows, summary=summary)

    def get_one(self, db: Session, tracked_id: int) -> Optional[TrackedCandidateOut]:
        row = db.get(TrackedCandidate, tracked_id)
        if row is None:
            return None
        return _to_out(row)

    def close(
        self,
        db: Session,
        tracked_id: int,
        *,
        reason: str = "manual",
    ) -> Optional[TrackedCandidateOut]:
        row = db.get(TrackedCandidate, tracked_id)
        if row is None:
            return None
        if row.status == "open":
            # Refresh once before close.
            self.refresh_one(db, tracked_id)
            row = db.get(TrackedCandidate, tracked_id)
            assert row is not None
            row.status = "closed"
            row.closed_at = _now()
            row.close_reason = reason
            db.commit()
            db.refresh(row)
        return _to_out(row)

    def refresh_one(self, db: Session, tracked_id: int) -> Optional[TrackedCandidateOut]:
        row = db.get(TrackedCandidate, tracked_id)
        if row is None:
            return None
        if row.status != "open":
            return _to_out(row)

        mark_net, underlying_price, notes = self._mark_position(
            db, row, force_refresh=True
        )
        self._record_mark(
            db,
            row,
            mark_net=mark_net,
            underlying_price=underlying_price,
            notes=notes,
        )
        self._maybe_auto_close(db, row)
        db.refresh(row)
        return _to_out(row)

    def refresh_all_open(self, db: Session) -> TrackedListResponse:
        """Mark every open position with one chain fetch per underlying.

        Starter-tier Massive plans rate-limit hard. Refreshing N SPY positions
        must not fire N full chain downloads — share one snapshot per symbol.
        """
        open_rows = list(
            db.scalars(
                select(TrackedCandidate).where(TrackedCandidate.status == "open")
            )
        )
        by_symbol: dict[str, list[TrackedCandidate]] = defaultdict(list)
        for row in open_rows:
            by_symbol[row.underlying_symbol.upper()].append(row)

        for symbol, rows in by_symbol.items():
            contracts, underlying_price, chain_note = self._load_shared_mark_chain(
                db, symbol, rows
            )
            for row in rows:
                mark_net, price, notes = self._mark_position(
                    db,
                    row,
                    contracts=contracts,
                    underlying_price=underlying_price,
                    force_refresh=False,
                )
                if chain_note and notes:
                    notes = f"{chain_note}; {notes}"
                elif chain_note:
                    notes = chain_note
                self._record_mark(
                    db,
                    row,
                    mark_net=mark_net,
                    underlying_price=price,
                    notes=notes,
                )
                self._maybe_auto_close(db, row)

        return self.list_tracked(db)

    def _load_shared_mark_chain(
        self,
        db: Session,
        symbol: str,
        rows: list[TrackedCandidate],
    ) -> tuple[list[OptionContractSnapshot], Optional[float], str]:
        """One chain pull for all open marks on a symbol (cache-friendly)."""
        today = _now().date()
        active = [r for r in rows if r.expiration_date > today]
        if not active:
            return [], None, "All positions expired — settling intrinsically"

        min_exp = min(r.expiration_date for r in active)
        max_exp = max(r.expiration_date for r in active)
        min_dte = max((min_exp - today).days - 2, 0)
        max_dte = max((max_exp - today).days + 2, 7)

        # Prefer a single live refresh; on 429 fall back to cache so marks still move.
        try:
            chain = self.chain_service.get_chain(
                db,
                symbol,
                min_dte=min_dte,
                max_dte=max_dte,
                force_refresh=True,
                include_rejected=True,
                sort_by_liquidity=False,
            )
            note = "Shared chain mark (1 fetch for symbol)"
            if chain.from_cache:
                note = "Shared chain mark (cache)"
            return list(chain.contracts), chain.underlying_price, note
        except MassiveAPIError as exc:
            if exc.status_code != 429:
                raise
            # Wait briefly, then use whatever is already cached.
            time.sleep(3)
            chain = self.chain_service.get_chain(
                db,
                symbol,
                min_dte=min_dte,
                max_dte=max_dte,
                force_refresh=False,
                include_rejected=True,
                sort_by_liquidity=False,
            )
            return (
                list(chain.contracts),
                chain.underlying_price,
                "Rate limited — marked from cache; retry in ~1 minute for a live mark",
            )

    def _mark_position(
        self,
        db: Session,
        row: TrackedCandidate,
        *,
        contracts: Optional[list[OptionContractSnapshot]] = None,
        underlying_price: Optional[float] = None,
        force_refresh: bool = False,
    ) -> tuple[Optional[float], Optional[float], str]:
        legs = _legs_from_json(row.legs_json)
        today = _now().date()

        # At/after expiration the option chain no longer returns these contracts,
        # so a chain-based mark fails. Settle at intrinsic value from the
        # underlying price so the position gets a real final P/L before it is
        # auto-closed for expiration.
        if row.expiration_date <= today:
            price = underlying_price or self._latest_underlying_price(
                row.underlying_symbol
            )
            if price is None:
                return (
                    None,
                    row.latest_underlying_price,
                    "Expired — underlying price unavailable for settlement",
                )
            mark_net = _settlement_mark_net(legs, price, row.is_credit)
            return mark_net, price, "Settled at expiration (intrinsic value)"

        if contracts is None:
            dte = max((row.expiration_date - today).days, 0)
            try:
                chain = self.chain_service.get_chain(
                    db,
                    row.underlying_symbol,
                    min_dte=max(dte - 2, 0),
                    max_dte=dte + 2 if dte > 0 else 7,
                    force_refresh=force_refresh,
                    include_rejected=True,
                    sort_by_liquidity=False,
                )
            except MassiveAPIError as exc:
                if exc.status_code == 429 and force_refresh:
                    # Fall back to cache instead of failing the whole refresh.
                    chain = self.chain_service.get_chain(
                        db,
                        row.underlying_symbol,
                        min_dte=max(dte - 2, 0),
                        max_dte=dte + 2 if dte > 0 else 7,
                        force_refresh=False,
                        include_rejected=True,
                        sort_by_liquidity=False,
                    )
                else:
                    raise

            contracts = [
                c
                for c in chain.contracts
                if c.expiration_date == row.expiration_date
            ]
            underlying_price = chain.underlying_price
            if not contracts:
                chain = self.chain_service.get_chain(
                    db,
                    row.underlying_symbol,
                    expiration_from=row.expiration_date,
                    expiration_to=row.expiration_date,
                    min_dte=0,
                    max_dte=400,
                    force_refresh=False,
                    include_rejected=True,
                    sort_by_liquidity=False,
                )
                contracts = list(chain.contracts)
                underlying_price = chain.underlying_price
        else:
            contracts = [
                c for c in contracts if c.expiration_date == row.expiration_date
            ]

        by_symbol = {c.symbol: c for c in contracts}
        notes: list[str] = []
        credit_parts = 0.0
        debit_parts = 0.0
        missing = 0

        for leg in legs:
            contract = by_symbol.get(leg.contract_symbol)
            if contract is None:
                contract = self._match_leg(contracts, leg)
            if contract is None:
                missing += 1
                continue
            # Mark-to-market: close the position (reverse actions).
            close_action = "buy" if leg.action == "sell" else "sell"
            try:
                price, _, price_notes = _leg_price(contract, close_action, slippage=0.02)
            except ValueError:
                missing += 1
                continue
            notes.extend(price_notes)
            if close_action == "buy":
                debit_parts += price * leg.quantity
            else:
                credit_parts += price * leg.quantity

        # A defined-risk spread mark is only trustworthy when every leg is
        # priced. If any leg is missing, return no mark so the previous P/L is
        # preserved (rather than reporting a misleading partial mark).
        if missing > 0:
            notes.append(f"Unreliable mark: {missing} of {len(legs)} leg(s) unpriced")
            return None, underlying_price, "; ".join(dict.fromkeys(notes))

        # Debit to exit shorts minus credit from selling longs.
        cost_to_close = debit_parts - credit_parts
        if row.is_credit:
            # Store cost to close; P/L = entry_credit - cost_to_close.
            mark_net = cost_to_close
        else:
            # Store exit proceeds; P/L = exit_proceeds - entry_debit.
            mark_net = -cost_to_close

        return mark_net, underlying_price, "; ".join(dict.fromkeys(notes))

    def _latest_underlying_price(self, symbol: str) -> Optional[float]:
        try:
            return self.chain_service.client.get_underlying_price(symbol.upper())
        except Exception:
            return None

    def _match_leg(
        self,
        contracts: list[OptionContractSnapshot],
        leg: OptionLeg,
    ) -> Optional[OptionContractSnapshot]:
        for contract in contracts:
            if (
                contract.contract_type == leg.contract_type
                and contract.expiration_date == leg.expiration_date
                and abs(contract.strike - leg.strike) < 0.011
            ):
                return contract
        return None

    def _pnl_from_mark(self, row: TrackedCandidate, mark_net: float) -> float:
        if row.is_credit:
            # Paid mark_net to close; received entry_net at open.
            return row.entry_net - mark_net
        # Debit: received mark_net to exit; paid entry_net at open.
        return mark_net - row.entry_net

    def _record_mark(
        self,
        db: Session,
        row: TrackedCandidate,
        *,
        mark_net: Optional[float],
        underlying_price: Optional[float],
        notes: str,
    ) -> None:
        now = _now()
        days = max((now.date() - row.tracked_at.date()).days, 0)
        pnl = None
        pnl_pct = None
        if mark_net is not None:
            pnl = self._pnl_from_mark(row, mark_net)
            if row.max_profit and row.max_profit > 0:
                pnl_pct = pnl / row.max_profit

        mark = CandidateMark(
            tracked_candidate_id=row.id,
            marked_at=now,
            days_since_entry=days,
            underlying_price=underlying_price,
            mark_net=mark_net,
            pnl=pnl,
            pnl_pct_of_max_profit=pnl_pct,
            notes=notes or None,
        )
        db.add(mark)

        # Always record that we attempted a mark.
        row.latest_marked_at = now
        if underlying_price is not None:
            row.latest_underlying_price = underlying_price

        # Only update P/L-derived fields on a trustworthy mark. A transient data
        # gap (None mark_net) must not wipe the last known good P/L.
        if pnl is not None:
            row.latest_pnl = pnl
            row.latest_mark_net = mark_net

            if days >= 1 and row.pnl_1d is None:
                row.pnl_1d = pnl
            if days >= 3 and row.pnl_3d is None:
                row.pnl_3d = pnl
            if days >= 7 and row.pnl_7d is None:
                row.pnl_7d = pnl
            if days >= 14 and row.pnl_14d is None:
                row.pnl_14d = pnl

            if (
                row.max_profit
                and row.max_profit > 0
                and pnl >= 0.5 * row.max_profit
            ):
                row.hit_50pct_profit = True
            if row.max_loss and row.max_loss > 0 and pnl <= -row.max_loss:
                row.hit_max_loss = True

        db.commit()

    def _maybe_auto_close(self, db: Session, row: TrackedCandidate) -> None:
        today = _now().date()
        if row.expiration_date <= today:
            row.status = "closed"
            row.closed_at = _now()
            row.close_reason = "expiration"
            db.commit()
            return
        if row.hit_max_loss:
            row.status = "closed"
            row.closed_at = _now()
            row.close_reason = "max_loss"
            db.commit()
