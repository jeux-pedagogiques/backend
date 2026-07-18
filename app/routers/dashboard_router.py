"""Dashboard router — professor analytics endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.services.dashboard_service import (
    get_overview,
    get_session_details,
    get_session_comparison,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def dashboard_overview(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Global dashboard stats for the current professor."""
    return get_overview(session, current_user.id)


@router.get("/sessions/{session_id}/details")
def dashboard_session_details(
    session_id: int,
    type: str = Query("quiz", regex="^(quiz|pitching)$"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Detailed results for a specific session."""
    result = get_session_details(session, current_user.id, session_id, type)
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )
    return result


@router.get("/sessions/{session_id}/comparison")
def dashboard_session_comparison(
    session_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Compare a session with previous sessions on the same module."""
    result = get_session_comparison(session, current_user.id, session_id)
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    return result
