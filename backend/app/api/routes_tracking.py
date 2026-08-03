from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.massive_client import MassiveAPIError
from app.db.database import get_db
from app.schemas.tracking import TrackCandidateRequest, TrackedCandidateOut, TrackedListResponse
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


@router.get("", response_model=TrackedListResponse)
def list_tracked(db: Session = Depends(get_db)) -> TrackedListResponse:
    return TrackingService().list_tracked(db)


@router.post("", response_model=TrackedCandidateOut)
def track_candidate(
    request: TrackCandidateRequest,
    db: Session = Depends(get_db),
) -> TrackedCandidateOut:
    return TrackingService().track(db, request.candidate)


@router.get("/{tracked_id}", response_model=TrackedCandidateOut)
def get_tracked(tracked_id: int, db: Session = Depends(get_db)) -> TrackedCandidateOut:
    result = TrackingService().get_one(db, tracked_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Tracked candidate not found")
    return result


@router.post("/{tracked_id}/refresh", response_model=TrackedCandidateOut)
def refresh_tracked(tracked_id: int, db: Session = Depends(get_db)) -> TrackedCandidateOut:
    try:
        result = TrackingService().refresh_one(db, tracked_id)
    except MassiveAPIError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Tracked candidate not found")
    return result


@router.post("/refresh-all", response_model=TrackedListResponse)
def refresh_all_open(db: Session = Depends(get_db)) -> TrackedListResponse:
    try:
        return TrackingService().refresh_all_open(db)
    except MassiveAPIError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{tracked_id}/close", response_model=TrackedCandidateOut)
def close_tracked(tracked_id: int, db: Session = Depends(get_db)) -> TrackedCandidateOut:
    try:
        result = TrackingService().close(db, tracked_id, reason="manual")
    except MassiveAPIError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Tracked candidate not found")
    return result
