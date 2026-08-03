"""Orchestrate chain fetch + strategy generation + EV scoring."""

from __future__ import annotations

from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session

from app.analytics.ev_engine import score_candidates_ev
from app.analytics.scoring import score_candidates
from app.analytics.settings import liquidity_settings_from_config
from app.analytics.strategy_builder import build_strategies
from app.config import get_settings
from app.data.massive_client import MassiveClient
from app.schemas.strategy import ScreenRequest, ScreenResponse, StrategyCandidate
from app.services.chain_service import ChainService
from app.services.volatility_service import VolatilityService


class ScreenerService:
    def __init__(self, client: Optional[MassiveClient] = None):
        self.client = client or MassiveClient()
        self.chain_service = ChainService(client=self.client)
        self.volatility_service = VolatilityService(client=self.client)

    def screen(self, db: Session, request: ScreenRequest) -> ScreenResponse:
        settings = get_settings()
        warnings = [settings.data_delay_warning]
        # Roadmap §14: with no event-calendar data source, surface a standing
        # event-risk warning. Earnings/ex-dividend inside the holding window can
        # invalidate the volatility forecast and short-premium assumptions.
        warnings.append(
            "Event calendar unavailable — verify earnings and ex-dividend dates "
            "before each expiration manually. Avoid short premium through earnings."
        )
        all_candidates: list[StrategyCandidate] = []
        symbols_scanned: list[str] = []

        for symbol in request.symbols:
            ticker = symbol.strip().upper()
            if not ticker:
                continue
            symbols_scanned.append(ticker)

            chain = self.chain_service.get_chain(
                db,
                ticker,
                min_dte=request.dte_min,
                max_dte=request.dte_max,
                force_refresh=request.force_refresh,
                include_rejected=False,
                sort_by_liquidity=False,
            )
            warnings.extend(
                w
                for w in chain.warnings
                if w not in warnings and w != settings.data_delay_warning
            )

            vol = self.volatility_service.get_metrics(
                db, ticker, force_refresh=request.force_refresh
            )
            warnings.extend(
                w
                for w in vol.warnings
                if w not in warnings and w != settings.data_delay_warning
            )

            candidates = build_strategies(
                chain.contracts,
                underlying_symbol=ticker,
                underlying_price=chain.underlying_price or vol.underlying_price,
                strategy_types=request.strategy_types,
                liquidity_settings=liquidity_settings_from_config(settings),
                slippage=0.02,
                max_candidates_per_strategy=request.max_candidates_per_strategy,
                min_credit_to_width=settings.min_credit_to_width,
                min_leg_liquidity_score=settings.min_strategy_liquidity_score,
                swing_dte_prefer_min=settings.swing_dte_prefer_min,
                swing_dte_prefer_max=settings.swing_dte_prefer_max,
            )

            candidates = score_candidates_ev(
                candidates,
                forecast_rv=vol.forecast_rv_30d,
                iv30=vol.iv30,
                commission_per_contract=0.65,
            )
            candidates = score_candidates(
                candidates,
                vol_score_short=vol.vol_score_short,
                vol_score_long=vol.vol_score_long,
                iv_rank=vol.iv_rank_52w,
                iv_percentile=vol.iv_percentile_52w,
                iv_history_count=vol.iv_history_count,
                scoring_profile=request.scoring_profile,
                max_risk_per_trade=request.max_risk_per_trade,
            )

            before = len(candidates)
            candidates = _quality_filter(candidates, settings)
            if before and len(candidates) < before:
                warnings.append(
                    f"{ticker}: filtered {before - len(candidates)} candidates without "
                    "positive modeled EV/Alpha or adequate liquidity — showing edge-only plays."
                )

            _append_regime_hint(warnings, vol)
            all_candidates.extend(candidates)

            if not candidates:
                warnings.append(
                    f"No strategy candidates for {ticker} with current filters "
                    f"and strategy types {request.strategy_types}."
                )

        # Rank by composite final score, then probability of profit (prefer
        # higher-POP trades among similar scores), then Alpha and liquidity.
        all_candidates.sort(
            key=lambda c: (
                c.final_score if c.final_score is not None else -1.0,
                c.pop_physical if c.pop_physical is not None else -1.0,
                c.alpha if c.alpha is not None else -999.0,
                c.liquidity_score,
            ),
            reverse=True,
        )

        all_candidates = _diversify_ranking(all_candidates)

        return ScreenResponse(
            candidates=all_candidates,
            warnings=warnings,
            symbols_scanned=symbols_scanned,
        )


def _quality_filter(
    candidates: list[StrategyCandidate],
    settings,
) -> list[StrategyCandidate]:
    """Keep only candidates with modeled edge and tradeable liquidity."""
    kept: list[StrategyCandidate] = []
    for cand in candidates:
        if cand.liquidity_score < settings.min_strategy_liquidity_score:
            continue
        if settings.require_positive_ev and (
            cand.ev_physical is None or cand.ev_physical <= 0
        ):
            continue
        if settings.require_positive_alpha and (
            cand.alpha is None or cand.alpha <= 0
        ):
            continue
        if cand.final_score is None or cand.final_score < settings.min_final_score:
            continue
        kept.append(cand)
    return kept


def _append_regime_hint(warnings: list[str], vol) -> None:
    vs = vol.vol_score_short
    vl = vol.vol_score_long
    if vs is None or vl is None:
        return
    gap = vl - vs
    if gap >= 8:
        msg = (
            "Vol regime favors long-vol / debit structures (forecast RV > implied). "
            "Short-premium ranks lower unless IV context improves."
        )
    elif gap <= -8:
        msg = (
            "Vol regime favors short-premium / credit structures (IV > forecast RV). "
            "Debit spreads rank lower unless volatility expands."
        )
    else:
        msg = "Vol regime is mixed — compare both credit and debit structures."
    if msg not in warnings:
        warnings.append(msg)


def _diversify_ranking(
    candidates: list[StrategyCandidate], score_band: float = 6.0
) -> list[StrategyCandidate]:
    """Interleave strategy types among near-tied candidates.

    Candidates are assumed pre-sorted by score (desc). We repeatedly consider all
    candidates whose final_score is within ``score_band`` of the best remaining
    candidate and emit the one whose strategy type is least represented so far
    (ties broken by score). This keeps clear winners on top while preventing a
    single strategy type from monopolizing the head of the list when scores are
    effectively tied — directly improving perceived diversity.
    """
    if len(candidates) <= 2:
        return candidates

    remaining = list(candidates)
    ordered: list[StrategyCandidate] = []
    counts: Counter[str] = Counter()

    while remaining:
        top_score = remaining[0].final_score or 0.0
        band_end = 0
        for idx, cand in enumerate(remaining):
            if (cand.final_score or 0.0) >= top_score - score_band:
                band_end = idx
            else:
                break
        band = remaining[: band_end + 1]
        pick_idx = min(
            range(len(band)),
            key=lambda i: (
                counts[band[i].strategy_type],
                -(band[i].final_score or 0.0),
            ),
        )
        picked = remaining.pop(pick_idx)
        counts[picked.strategy_type] += 1
        ordered.append(picked)

    return ordered
