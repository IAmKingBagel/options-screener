from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.massive_client import MassiveAPIError
from app.db.database import get_db
from app.schemas.option import OptionChainResponse
from app.services.chain_service import ChainService

router = APIRouter(prefix="/api/chain", tags=["chain"])


@router.get("/{symbol}", response_model=OptionChainResponse)
def get_option_chain(
    symbol: str,
    expiration_from: Optional[date] = Query(default=None),
    expiration_to: Optional[date] = Query(default=None),
    min_dte: Optional[int] = Query(default=None, ge=0),
    max_dte: Optional[int] = Query(default=None, ge=0),
    force_refresh: bool = Query(default=False),
    include_rejected: bool = Query(
        default=False,
        description="Include contracts that fail liquidity gates.",
    ),
    liquidity_strict: bool = Query(
        default=False,
        description="Require minimum volume in addition to open interest.",
    ),
    sort_by_liquidity: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> OptionChainResponse:
    """
    Fetch and return a normalized option chain for the underlying symbol.

    Data may be delayed (Massive Options Starter). Intended for swing-trade screening.
    """
    settings = get_settings()
    service = ChainService()

    try:
        chain = service.get_chain(
            db,
            symbol,
            expiration_from=expiration_from,
            expiration_to=expiration_to,
            min_dte=min_dte,
            max_dte=max_dte,
            force_refresh=force_refresh,
            include_rejected=include_rejected,
            liquidity_strict=liquidity_strict,
            sort_by_liquidity=sort_by_liquidity,
        )
    except MassiveAPIError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    if settings.data_delay_warning not in chain.warnings:
        chain.warnings.insert(0, settings.data_delay_warning)

    return chain
