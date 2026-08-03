"""Option chain fetch, normalization, filtering, and caching."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.analytics.liquidity import enrich_contracts
from app.analytics.settings import liquidity_settings_from_config
from app.data.cache import get_recent_snapshot
from app.data.massive_client import MassiveAPIError, MassiveClient
from app.data.providers import normalize_massive_chain
from app.schemas.option import OptionChainResponse, OptionContractSnapshot
from app.services.snapshot_service import store_chain_snapshot


def _build_massive_params(
    *,
    expiration_from: Optional[date] = None,
    expiration_to: Optional[date] = None,
    min_dte: Optional[int] = None,
    max_dte: Optional[int] = None,
    strike_low: Optional[float] = None,
    strike_high: Optional[float] = None,
) -> dict[str, Any]:
    """Translate dashboard filters into Massive query parameters where possible."""
    params: dict[str, Any] = {"limit": 250}
    today = datetime.now(timezone.utc).date()

    if expiration_from:
        params["expiration_date.gte"] = expiration_from.isoformat()
    elif min_dte is not None:
        params["expiration_date.gte"] = (today + timedelta(days=min_dte)).isoformat()

    if expiration_to:
        params["expiration_date.lte"] = expiration_to.isoformat()
    elif max_dte is not None:
        params["expiration_date.lte"] = (today + timedelta(days=max_dte)).isoformat()

    # Bounding strikes around spot keeps ATM strikes in the paginated result and
    # lets the page budget span every expiration in the window (see get_chain).
    if strike_low is not None:
        params["strike_price.gte"] = round(strike_low, 2)
    if strike_high is not None:
        params["strike_price.lte"] = round(strike_high, 2)

    return params


def _filter_contracts(
    contracts: list[OptionContractSnapshot],
    *,
    min_dte: Optional[int] = None,
    max_dte: Optional[int] = None,
    expiration_from: Optional[date] = None,
    expiration_to: Optional[date] = None,
) -> list[OptionContractSnapshot]:
    filtered: list[OptionContractSnapshot] = []
    for contract in contracts:
        if min_dte is not None and contract.dte < min_dte:
            continue
        if max_dte is not None and contract.dte > max_dte:
            continue
        if expiration_from and contract.expiration_date < expiration_from:
            continue
        if expiration_to and contract.expiration_date > expiration_to:
            continue
        filtered.append(contract)
    return filtered


def _finalize_contracts(
    contracts: list[OptionContractSnapshot],
    *,
    include_rejected: bool = False,
    liquidity_strict: bool = False,
    sort_by_liquidity: bool = True,
) -> tuple[list[OptionContractSnapshot], int, int]:
    """Enrich contracts with liquidity metrics; return (visible, liquid_count, rejected_count)."""
    settings = get_settings()
    liq_settings = liquidity_settings_from_config(settings)
    if liquidity_strict:
        liq_settings = replace(liq_settings, require_volume=True)

    # Enrich exactly once, then derive visible/counts from the enriched set.
    enriched_all = enrich_contracts(
        contracts,
        settings=liq_settings,
        include_rejected=True,
        sort_by_liquidity=False,
    )
    liquid_count = sum(1 for c in enriched_all if c.passes_liquidity)
    rejected_count = len(enriched_all) - liquid_count

    visible = enriched_all if include_rejected else [c for c in enriched_all if c.passes_liquidity]
    if sort_by_liquidity:
        visible = sorted(
            visible,
            key=lambda c: (c.liquidity_score or 0.0, c.open_interest or 0),
            reverse=True,
        )
    return visible, liquid_count, rejected_count


class ChainService:
    def __init__(self, client: Optional[MassiveClient] = None):
        self.client = client or MassiveClient()

    def get_chain(
        self,
        db: Session,
        symbol: str,
        *,
        expiration_from: Optional[date] = None,
        expiration_to: Optional[date] = None,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        force_refresh: bool = False,
        include_raw_payload: bool = False,
        include_rejected: bool = False,
        liquidity_strict: bool = False,
        sort_by_liquidity: bool = True,
        strike_band_pct: Optional[float] = None,
    ) -> OptionChainResponse:
        settings = get_settings()
        underlying = symbol.upper()
        min_dte = min_dte if min_dte is not None else settings.default_min_dte
        max_dte = max_dte if max_dte is not None else settings.default_max_dte

        warnings = [settings.data_delay_warning]

        if not force_refresh:
            cached = get_recent_snapshot(db, underlying)
            if cached is not None:
                filtered = _filter_contracts(
                    cached.contracts,
                    min_dte=min_dte,
                    max_dte=max_dte,
                    expiration_from=expiration_from,
                    expiration_to=expiration_to,
                )
                visible, liquid_count, rejected_count = _finalize_contracts(
                    filtered,
                    include_rejected=include_rejected,
                    liquidity_strict=liquidity_strict,
                    sort_by_liquidity=sort_by_liquidity,
                )
                cached.contracts = visible
                cached.contract_count = len(visible)
                cached.liquid_contract_count = liquid_count
                cached.rejected_contract_count = rejected_count
                cached.warnings = warnings
                return cached

        # Fetch spot first so we can bound the strike window. A single expiration's
        # deep strikes can otherwise exhaust the page budget before later
        # expirations are reached (and drop ATM strikes entirely).
        try:
            underlying_price = self.client.get_underlying_price(underlying)
        except MassiveAPIError:
            raise

        band = strike_band_pct if strike_band_pct is not None else settings.chain_strike_band_pct
        strike_low = strike_high = None
        # Only bound strikes when we're spanning multiple expirations by DTE.
        # Expiration-pinned lookups (e.g. tracking a specific spread) skip bounding
        # so exact leg strikes are never excluded.
        bound_strikes = (
            band
            and band > 0
            and underlying_price
            and underlying_price > 0
            and expiration_from is None
            and expiration_to is None
        )
        if bound_strikes:
            strike_low = underlying_price * (1 - band)
            strike_high = underlying_price * (1 + band)

        params = _build_massive_params(
            expiration_from=expiration_from,
            expiration_to=expiration_to,
            min_dte=min_dte,
            max_dte=max_dte,
            strike_low=strike_low,
            strike_high=strike_high,
        )

        raw_payload = self.client.get_option_chain_snapshot(
            underlying, params=params, max_pages=settings.chain_max_pages
        )

        # Normalize once without override to detect a live snapshot price, then
        # fall back to the previous close (also used for strike bounding above).
        contracts, snapshot_price, normalize_warnings = normalize_massive_chain(
            raw_payload,
            include_raw_payload=include_raw_payload,
            underlying_price_override=None,
        )
        warnings.extend(normalize_warnings)

        if snapshot_price is not None:
            underlying_price = snapshot_price
        if underlying_price is not None:
            # Ensure every contract carries a spot for moneyness / far-OTM checks.
            contracts = [
                c if c.underlying_price is not None
                else c.model_copy(update={"underlying_price": underlying_price})
                for c in contracts
            ]

        if raw_payload.get("truncated"):
            warnings.append(
                f"Chain truncated after {raw_payload.get('pages_fetched', '?')} pages. "
                "Some far expirations or strikes may be missing."
            )

        contracts = _filter_contracts(
            contracts,
            min_dte=min_dte,
            max_dte=max_dte,
            expiration_from=expiration_from,
            expiration_to=expiration_to,
        )

        if not contracts:
            warnings.append("No contracts matched the requested filters.")

        visible, liquid_count, rejected_count = _finalize_contracts(
            contracts,
            include_rejected=include_rejected,
            liquidity_strict=liquidity_strict,
            sort_by_liquidity=sort_by_liquidity,
        )

        # Store the full DTE-filtered set (liquid + rejected) so cache hits can
        # recompute liquid/rejected counts accurately and serve include_rejected
        # requests consistently. Bounded strikes keep this set small.
        run = store_chain_snapshot(
            db,
            underlying_symbol=underlying,
            underlying_price=underlying_price,
            contracts=contracts,
            raw_payload=None,
        )

        if rejected_count > 0 and not include_rejected:
            warnings.append(
                f"Filtered out {rejected_count} illiquid contracts "
                f"(showing {len(visible)} passing liquidity gates)."
            )

        return OptionChainResponse(
            underlying_symbol=underlying,
            underlying_price=underlying_price,
            fetched_at=run.fetched_at,
            provider="massive",
            snapshot_id=run.id,
            from_cache=False,
            contract_count=len(visible),
            liquid_contract_count=liquid_count,
            rejected_contract_count=rejected_count,
            warnings=warnings,
            contracts=visible,
        )
