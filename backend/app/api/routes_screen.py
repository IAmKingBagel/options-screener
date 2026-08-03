from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.massive_client import MassiveAPIError
from app.db.database import get_db
from app.schemas.strategy import ScreenRequest, ScreenResponse
from app.services.screener_service import ScreenerService

router = APIRouter(prefix="/api/screen", tags=["screen"])


@router.post("", response_model=ScreenResponse)
def screen_strategies(
    request: ScreenRequest,
    db: Session = Depends(get_db),
) -> ScreenResponse:
    """Generate and rank defined-risk strategy candidates for a watchlist."""
    if not request.symbols:
        raise HTTPException(status_code=400, detail="At least one symbol is required.")

    settings = get_settings()
    service = ScreenerService()

    try:
        result = service.screen(db, request)
    except MassiveAPIError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    if settings.data_delay_warning not in result.warnings:
        result.warnings.insert(0, settings.data_delay_warning)

    return result
