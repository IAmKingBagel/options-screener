"""Composite opportunity scoring, grades, and explanations."""

from __future__ import annotations

from typing import Optional

from app.analytics.greeks import aggregate_strategy_greeks, clamp, greek_efficiency_score
from app.schemas.strategy import StrategyCandidate

SHORT_PREMIUM_TYPES = {
    "bull_put_credit",
    "bear_call_credit",
    "iron_condor",
}
LONG_VOL_TYPES = {
    "bull_call_debit",
    "bear_put_debit",
}
# IV Rank / Percentile need enough stored snapshots to be meaningful. Below this,
# a bootstrapping IVR (often ~0 on the first days of logging) must NOT be taken at
# face value — it would wrongly tank otherwise-strong candidates.
MIN_IV_HISTORY_FOR_CONTEXT = 30


def alpha_score(alpha: Optional[float]) -> float:
    """Map Alpha = EV/max_loss to 0–100. alpha=0.02 -> 60, 0.05 -> 75, 0.10 -> 100."""
    if alpha is None:
        return 40.0
    return clamp(50 + 500 * alpha, 0, 100)


def risk_reward_score(candidate: StrategyCandidate) -> float:
    """Credit/width for credits; max_profit/max_loss for debits."""
    if candidate.is_credit and candidate.credit_to_width is not None:
        ctw = candidate.credit_to_width
        # Peak around 0.25–0.40
        if 0.25 <= ctw <= 0.40:
            return 90.0
        if 0.15 <= ctw < 0.25:
            return 70.0
        if 0.40 < ctw <= 0.50:
            return 75.0
        if ctw > 0.50:
            return 55.0  # unusually rich — possible data/model issue
        return 40.0

    if candidate.max_profit and candidate.max_loss and candidate.max_loss > 0:
        ratio = candidate.max_profit / candidate.max_loss
        return clamp(40 + 40 * ratio, 0, 100)
    return 50.0


def iv_context_score(
    *,
    iv_rank: Optional[float],
    iv_percentile: Optional[float],
    profile: str,
    iv_history_count: int = 0,
) -> float:
    # Neutral until IV history is deep enough for IVR/IVP to mean anything.
    if iv_history_count < MIN_IV_HISTORY_FOR_CONTEXT:
        return 50.0
    metric = iv_rank if iv_rank is not None else iv_percentile
    if metric is None:
        return 50.0
    if profile == "short_premium":
        return clamp(metric, 0, 100)
    if profile == "long_vol":
        return clamp(100 - metric, 0, 100)
    # Neutral: prefer not extreme
    return clamp(100 - abs(metric - 50), 0, 100)


def risk_penalty(
    candidate: StrategyCandidate,
    *,
    iv_history_count: int = 0,
    max_risk_per_trade: Optional[float] = None,
    vol_score_short: Optional[float] = None,
    vol_score_long: Optional[float] = None,
) -> tuple[float, list[str]]:
    """Return (penalty points to subtract, warning messages)."""
    penalty = 0.0
    notes: list[str] = []

    if candidate.dte < 7:
        penalty += 30
        notes.append("Short DTE penalty")
    elif candidate.dte < 14:
        penalty += 10
        notes.append("Below preferred swing DTE")

    # Starter-tier data limitations affect every contract — penalize once, lightly.
    # IV context already returns neutral 50 when history is thin; do not double-penalize.
    has_delayed_data = any(
        "No bid/ask" in w or "day-bar" in w for w in candidate.warnings
    )
    if has_delayed_data:
        penalty += 3
        notes.append("Delayed data — confirm live quotes before trading")

    if iv_history_count < 120 and iv_history_count >= MIN_IV_HISTORY_FOR_CONTEXT:
        penalty += 3
        notes.append("IV history still maturing")

    if candidate.ev_physical is not None and candidate.ev_physical < 0:
        penalty += 12
        notes.append("Negative modeled EV")

    if (
        candidate.pop_physical is not None
        and candidate.ev_physical is not None
        and candidate.pop_physical > 0.6
        and candidate.ev_physical < 0
    ):
        penalty += 8
        notes.append("High POP / negative EV asymmetry")

    # Vol regime misalignment: don't rank short premium highly when long-vol is favored.
    if vol_score_short is not None and vol_score_long is not None:
        gap = vol_score_long - vol_score_short
        if gap >= 8 and candidate.strategy_type in SHORT_PREMIUM_TYPES:
            penalty += 10
            notes.append("Short premium misaligned with vol regime (long-vol favored)")
        elif gap <= -8 and candidate.strategy_type in LONG_VOL_TYPES:
            penalty += 10
            notes.append("Debit/long-vol misaligned with vol regime (short-premium favored)")

    if max_risk_per_trade is not None and candidate.max_loss is not None:
        # max_loss is per share; contract risk ≈ max_loss * 100
        contract_risk = candidate.max_loss * 100
        if contract_risk > max_risk_per_trade:
            penalty += 50
            notes.append("Max loss above risk limit")

    # Short calls: assignment/dividend placeholder
    if any(
        leg.action == "sell" and leg.contract_type == "call" for leg in candidate.legs
    ):
        penalty += 5
        notes.append("Short call assignment risk (verify ex-div)")

    return penalty, notes


def grade_from_score(final_score: float) -> str:
    if final_score >= 90:
        return "A"
    if final_score >= 80:
        return "B"
    if final_score >= 70:
        return "C"
    if final_score >= 60:
        return "D"
    return "F"


def resolve_profile(candidate: StrategyCandidate, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    if candidate.strategy_type in SHORT_PREMIUM_TYPES:
        return "short_premium"
    if candidate.strategy_type in LONG_VOL_TYPES:
        return "long_vol"
    return "neutral"


def explanation_generator(
    candidate: StrategyCandidate,
    *,
    profile: str,
    vol_score: float,
    breakdown: dict,
) -> str:
    parts: list[str] = []

    if candidate.alpha is not None and candidate.alpha > 0:
        parts.append(
            "Modeled positive expectancy under forecast realized volatility "
            f"(Alpha={candidate.alpha:.3f})."
        )
    elif candidate.alpha is not None:
        parts.append(
            f"Non-positive modeled expectancy (Alpha={candidate.alpha:.3f}) "
            "under current assumptions."
        )

    # Surface the EV/POP detail (previously computed in the EV engine but lost
    # when this generator overwrote the explanation).
    ev_bits: list[str] = []
    if candidate.ev_physical is not None and candidate.max_loss:
        ev_bits.append(
            f"EV={candidate.ev_physical:.3f}/share vs max loss {candidate.max_loss:.2f}"
        )
    if candidate.pop_physical is not None:
        ev_bits.append(f"POP~{candidate.pop_physical * 100:.0f}%")
    if ev_bits:
        parts.append("Physical model: " + ", ".join(ev_bits) + ".")

    if profile == "short_premium" and vol_score >= 60:
        parts.append("Volatility edge detected favoring short-premium structures.")
    elif profile == "long_vol" and vol_score >= 60:
        parts.append("Volatility context favors long-vol / debit structures.")

    if candidate.liquidity_score >= 70:
        parts.append("Liquidity quality is acceptable for screening.")
    elif candidate.liquidity_score < 50:
        parts.append("Liquidity is weak — confirm fills carefully.")

    grade = candidate.grade or grade_from_score(candidate.final_score or 0)
    if grade in {"A", "B"}:
        parts.append("Higher-ranked candidate under current assumptions.")
    elif grade == "F":
        parts.append("Watch only / reject under current scoring thresholds.")

    parts.append("Requires backtest confirmation. Not financial advice.")
    return " ".join(parts)


def apply_composite_score(
    candidate: StrategyCandidate,
    *,
    vol_score_short: Optional[float],
    vol_score_long: Optional[float],
    iv_rank: Optional[float] = None,
    iv_percentile: Optional[float] = None,
    iv_history_count: int = 0,
    scoring_profile: str = "auto",
    max_risk_per_trade: Optional[float] = None,
) -> StrategyCandidate:
    """Attach Greek score, composite final_score, grade, and explanation."""
    profile = resolve_profile(candidate, scoring_profile)

    # Refresh greek summary for consistency.
    candidate.greek_summary = aggregate_strategy_greeks(candidate.legs)
    greek_profile = "long_vol" if profile == "long_vol" else "short_premium"
    greek_score = greek_efficiency_score(candidate, profile=greek_profile)

    a_score = alpha_score(candidate.alpha)
    liq = clamp(candidate.liquidity_score, 0, 100)
    rr = risk_reward_score(candidate)
    iv_ctx = iv_context_score(
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        profile=profile,
        iv_history_count=iv_history_count,
    )

    if profile == "short_premium":
        vol_score = vol_score_short if vol_score_short is not None else 50.0
        final = (
            0.25 * vol_score
            + 0.25 * a_score
            + 0.20 * liq
            + 0.15 * greek_score
            + 0.10 * iv_ctx
            + 0.05 * rr
        )
    elif profile == "long_vol":
        vol_score = vol_score_long if vol_score_long is not None else 50.0
        final = (
            0.25 * vol_score
            + 0.25 * a_score
            + 0.20 * liq
            + 0.15 * greek_score
            + 0.10 * 50.0  # directional placeholder
            + 0.05 * rr
        )
    else:
        # Neutral research: blend vol scores toward alignment with strategy type.
        vs = vol_score_short if candidate.is_credit else vol_score_long
        vol_score = vs if vs is not None else 50.0
        final = (
            0.30 * a_score
            + 0.25 * liq
            + 0.20 * vol_score
            + 0.15 * greek_score
            + 0.10 * rr
        )

    penalty, penalty_notes = risk_penalty(
        candidate,
        iv_history_count=iv_history_count,
        max_risk_per_trade=max_risk_per_trade,
        vol_score_short=vol_score_short,
        vol_score_long=vol_score_long,
    )
    final = clamp(final - penalty, 0, 100)

    breakdown = {
        "profile": profile,
        "volatility_score": round(vol_score, 1),
        "alpha_score": round(a_score, 1),
        "liquidity_score": round(liq, 1),
        "greek_score": round(greek_score, 1),
        "iv_context_score": round(iv_ctx, 1),
        "risk_reward_score": round(rr, 1),
        "risk_penalty": round(penalty, 1),
        "final_score": round(final, 1),
    }

    candidate.greek_score = greek_score
    candidate.score_breakdown = breakdown
    candidate.final_score = round(final, 1)
    candidate.grade = grade_from_score(candidate.final_score)
    candidate.scoring_profile = profile

    for note in penalty_notes:
        if note not in candidate.warnings:
            candidate.warnings.append(note)

    candidate.explanation = explanation_generator(
        candidate,
        profile=profile,
        vol_score=vol_score,
        breakdown=breakdown,
    )
    return candidate


def score_candidates(
    candidates: list[StrategyCandidate],
    *,
    vol_score_short: Optional[float],
    vol_score_long: Optional[float],
    iv_rank: Optional[float] = None,
    iv_percentile: Optional[float] = None,
    iv_history_count: int = 0,
    scoring_profile: str = "auto",
    max_risk_per_trade: Optional[float] = None,
) -> list[StrategyCandidate]:
    scored = [
        apply_composite_score(
            candidate,
            vol_score_short=vol_score_short,
            vol_score_long=vol_score_long,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            iv_history_count=iv_history_count,
            scoring_profile=scoring_profile,
            max_risk_per_trade=max_risk_per_trade,
        )
        for candidate in candidates
    ]
    scored.sort(
        key=lambda c: (
            c.final_score if c.final_score is not None else -1,
            c.alpha if c.alpha is not None else -999,
            c.liquidity_score,
        ),
        reverse=True,
    )
    return scored
