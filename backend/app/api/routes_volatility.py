from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.massive_client import MassiveAPIError
from app.db.database import get_db
from app.schemas.volatility import VolatilityMetrics
from app.services.volatility_service import VolatilityService

router = APIRouter(prefix="/api/volatility", tags=["volatility"])


@router.get("/{symbol}", response_model=VolatilityMetrics)
def get_volatility_metrics(
    symbol: str,
    force_refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> VolatilityMetrics:
    """
    Realized vol, forecast RV, IV30, IV Rank/Percentile, and VRP for an underlying.
    """
    settings = get_settings()
    service = VolatilityService()

    try:
        metrics = service.get_metrics(db, symbol, force_refresh=force_refresh)
    except MassiveAPIError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    if settings.data_delay_warning not in metrics.warnings:
        metrics.warnings.insert(0, settings.data_delay_warning)

    return metrics
