"""Compute and persist volatility context for an underlying."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.iv_rank import (
    compute_iv_percentile,
    compute_iv_rank,
    estimate_iv30_from_chain,
    history_status,
    iv_regime_label,
)
from app.analytics.realized_vol import (
    realized_vol,
    variance_risk_premium,
    volatility_scores,
    weighted_forecast_rv,
)
from app.config import get_settings
from app.data.massive_client import MassiveAPIError, MassiveClient
from app.data.providers import normalize_massive_chain
from app.db.models import IvSnapshotHistory, UnderlyingDailyClose
from app.schemas.volatility import VolatilityMetrics


def _ms_to_date(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()


class VolatilityService:
    def __init__(self, client: Optional[MassiveClient] = None):
        self.client = client or MassiveClient()

    def get_metrics(
        self,
        db: Session,
        symbol: str,
        *,
        force_refresh: bool = False,
    ) -> VolatilityMetrics:
        settings = get_settings()
        underlying = symbol.upper()
        warnings = [settings.data_delay_warning]
        notes: list[str] = []
        now = datetime.now(timezone.utc)

        closes = self._load_or_fetch_closes(db, underlying, force_refresh=force_refresh)
        if len(closes) < 11:
            warnings.append(
                f"Insufficient daily close history ({len(closes)} bars). "
                "Need at least 11 closes for RV10."
            )

        close_prices = [c for _, c in closes]
        rv10 = realized_vol(close_prices, 10)
        rv20 = realized_vol(close_prices, 20)
        rv30 = realized_vol(close_prices, 30)
        rv60 = realized_vol(close_prices, 60)
        forecast = weighted_forecast_rv(rv10, rv20, rv60)

        underlying_price = close_prices[-1] if close_prices else self.client.get_underlying_price(
            underlying
        )

        contracts, chain_warnings = self._fetch_chain_contracts(underlying, underlying_price)
        warnings.extend(chain_warnings)

        iv30, atm_points, iv_warnings = estimate_iv30_from_chain(
            contracts,
            underlying_price=underlying_price,
        )
        warnings.extend(iv_warnings)

        vrp = variance_risk_premium(iv30, forecast)

        if iv30 is not None:
            self._store_iv_snapshot(
                db,
                symbol=underlying,
                snapshot_date=now.date(),
                iv30=iv30,
                underlying_price=underlying_price,
                forecast_rv_30d=forecast,
                vrp=vrp,
            )

        iv_history = self._load_iv_history(db, underlying)
        iv_history_count = len(iv_history)
        status = history_status(iv_history_count)

        iv_rank = None
        iv_percentile = None
        if iv30 is not None and iv_history_count > 0:
            # Exclude today's value from history for rank/percentile context.
            prior = [v for d, v in iv_history if d < now.date()]
            series = prior if prior else [v for _, v in iv_history]
            iv_rank = compute_iv_rank(iv30, series)
            iv_percentile = compute_iv_percentile(iv30, series)
        elif iv30 is not None:
            notes.append(
                "IV Rank / IV Percentile unavailable — no stored IV history yet. "
                "Snapshots accumulate each time you run this endpoint."
            )

        if status != "full_52w":
            notes.append(
                f"IV history status: {status} ({iv_history_count} daily snapshots). "
                "Need 252 trading days for full 52-week IVR/IVP."
            )

        vrp_history = [
            row.vrp
            for row in db.scalars(
                select(IvSnapshotHistory)
                .where(
                    IvSnapshotHistory.symbol == underlying,
                    IvSnapshotHistory.vrp.is_not(None),
                )
                .order_by(IvSnapshotHistory.snapshot_date.asc())
            )
            if row.vrp is not None
        ]
        vrp_z, vol_score_short, vol_score_long = volatility_scores(
            vrp, vrp_history=vrp_history
        )

        if iv30 is not None and forecast is not None:
            if vrp is not None and vrp > 0:
                notes.append(
                    "IV30 is above forecast RV (positive VRP) — favors short-premium "
                    "structures all else equal."
                )
            elif vrp is not None and vrp < 0:
                notes.append(
                    "IV30 is below forecast RV (negative VRP) — favors long-vol / debit "
                    "structures all else equal."
                )

        return VolatilityMetrics(
            symbol=underlying,
            as_of=now,
            underlying_price=underlying_price,
            realized_vol_10d=rv10,
            realized_vol_20d=rv20,
            realized_vol_30d=rv30,
            realized_vol_60d=rv60,
            forecast_rv_30d=forecast,
            iv30=iv30,
            atm_iv_points=atm_points,
            iv_rank_52w=iv_rank,
            iv_percentile_52w=iv_percentile,
            iv_history_count=iv_history_count,
            iv_history_status=status,
            iv_regime=iv_regime_label(iv_rank, iv_percentile),
            vrp=vrp,
            vrp_z=vrp_z,
            vol_score_short=vol_score_short,
            vol_score_long=vol_score_long,
            warnings=warnings,
            notes=notes,
        )

    def _load_or_fetch_closes(
        self,
        db: Session,
        symbol: str,
        *,
        force_refresh: bool,
        lookback_days: int = 120,
    ) -> list[tuple[date, float]]:
        existing = list(
            db.scalars(
                select(UnderlyingDailyClose)
                .where(UnderlyingDailyClose.symbol == symbol)
                .order_by(UnderlyingDailyClose.trade_date.asc())
            )
        )
        today = datetime.now(timezone.utc).date()
        need_fetch = force_refresh or len(existing) < 60
        # Refetch when the newest stored close is stale (covers weekends/holidays
        # with a 3-day grace). Previously stale-but-sufficient history was never
        # refreshed, so RV/forecast could silently run on outdated closes.
        if not need_fetch and existing:
            latest = existing[-1].trade_date
            if (today - latest).days > 3:
                need_fetch = True

        if need_fetch:
            start = (today - timedelta(days=lookback_days + 30)).isoformat()
            end = today.isoformat()
            try:
                bars = self.client.get_underlying_daily_bars(symbol, start, end)
            except MassiveAPIError:
                raise
            for bar in bars:
                ts = bar.get("t")
                close = bar.get("c")
                if ts is None or close is None:
                    continue
                trade_date = _ms_to_date(int(ts))
                self._upsert_close(db, symbol, trade_date, float(close))
            db.commit()
            existing = list(
                db.scalars(
                    select(UnderlyingDailyClose)
                    .where(UnderlyingDailyClose.symbol == symbol)
                    .order_by(UnderlyingDailyClose.trade_date.asc())
                )
            )

        return [(row.trade_date, row.close) for row in existing]

    def _upsert_close(
        self,
        db: Session,
        symbol: str,
        trade_date: date,
        close: float,
    ) -> None:
        row = db.scalar(
            select(UnderlyingDailyClose).where(
                UnderlyingDailyClose.symbol == symbol,
                UnderlyingDailyClose.trade_date == trade_date,
            )
        )
        if row is None:
            db.add(
                UnderlyingDailyClose(symbol=symbol, trade_date=trade_date, close=close)
            )
        else:
            row.close = close

    def _fetch_chain_contracts(self, symbol: str, underlying_price: Optional[float]):
        settings = get_settings()
        today = datetime.now(timezone.utc).date()
        params = {
            "limit": 250,
            "expiration_date.gte": (
                today + timedelta(days=settings.default_min_dte)
            ).isoformat(),
            "expiration_date.lte": (
                today + timedelta(days=settings.default_max_dte)
            ).isoformat(),
        }
        # Bound strikes tightly around spot so near-ATM contracts for every
        # expiration are present. Without this, pagination can drop ATM strikes
        # and IV30 gets estimated from a mispriced far strike (garbage IV).
        band = settings.volatility_strike_band_pct
        if underlying_price and underlying_price > 0 and band and band > 0:
            params["strike_price.gte"] = round(underlying_price * (1 - band), 2)
            params["strike_price.lte"] = round(underlying_price * (1 + band), 2)
        warnings: list[str] = []
        try:
            payload = self.client.get_option_chain_snapshot(
                symbol, params=params, max_pages=settings.volatility_max_pages
            )
        except MassiveAPIError as exc:
            warnings.append(f"Could not fetch option chain for IV30: {exc}")
            return [], warnings

        contracts, _, normalize_warnings = normalize_massive_chain(
            payload,
            underlying_price_override=underlying_price,
        )
        warnings.extend(normalize_warnings)
        return contracts, warnings

    def _store_iv_snapshot(
        self,
        db: Session,
        *,
        symbol: str,
        snapshot_date: date,
        iv30: float,
        underlying_price: Optional[float],
        forecast_rv_30d: Optional[float],
        vrp: Optional[float],
    ) -> None:
        row = db.scalar(
            select(IvSnapshotHistory).where(
                IvSnapshotHistory.symbol == symbol,
                IvSnapshotHistory.snapshot_date == snapshot_date,
            )
        )
        now = datetime.now(timezone.utc)
        if row is None:
            db.add(
                IvSnapshotHistory(
                    symbol=symbol,
                    snapshot_date=snapshot_date,
                    iv30=iv30,
                    underlying_price=underlying_price,
                    forecast_rv_30d=forecast_rv_30d,
                    vrp=vrp,
                    created_at=now,
                )
            )
        else:
            row.iv30 = iv30
            row.underlying_price = underlying_price
            row.forecast_rv_30d = forecast_rv_30d
            row.vrp = vrp
            row.created_at = now
        db.commit()

    def _load_iv_history(self, db: Session, symbol: str) -> list[tuple[date, float]]:
        rows = db.scalars(
            select(IvSnapshotHistory)
            .where(IvSnapshotHistory.symbol == symbol)
            .order_by(IvSnapshotHistory.snapshot_date.asc())
        )
        return [(row.snapshot_date, row.iv30) for row in rows]
