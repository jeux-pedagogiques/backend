import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.quiz_session import QuizSession, QuizParticipant, QuizAttempt
from app.services.socket_service import sio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quiz-sessions", tags=["quiz-sessions"])


@router.get("/{session_id}/leaderboard")
def get_session_leaderboard(
    session_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Retrieve the sorted leaderboard for a quiz session with average response times."""
    quiz_session = session.get(QuizSession, session_id)
    if not quiz_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Séance introuvable."
        )

    # Verify authorization (either the prof who created it, or a participant in the session)
    if quiz_session.prof_id != current_user.id:
        # Check if current user is participant (by checking if their username matches one of the participants)
        # Note: Guests join without logging in (no user_id), but logged in users might check the leaderboard.
        # Since anyone can view a leaderboard once the session is created, we allow it.
        pass

    # Fetch participants sorted by score_total descending
    statement = (
        select(QuizParticipant)
        .where(QuizParticipant.session_id == session_id)
        .order_by(QuizParticipant.score_total.desc())
    )
    participants = session.exec(statement).all()

    leaderboard = []
    for p in participants:
        # Calculate average response time
        statement_attempts = select(QuizAttempt).where(QuizAttempt.participant_id == p.id)
        attempts = session.exec(statement_attempts).all()
        
        avg_response_time = 0
        if attempts:
            total_time = sum(a.temps_reponse_ms for a in attempts)
            avg_response_time = round(total_time / len(attempts), 1)

        leaderboard.append({
            "participant_id": p.id,
            "pseudo": p.pseudo,
            "score_total": p.score_total,
            "is_active": p.is_active,
            "average_response_time_ms": avg_response_time,
            "total_answers": len(attempts),
            "correct_answers": sum(1 for a in attempts if a.est_correcte)
        })

    return leaderboard


@router.post("/{session_id}/end")
async def end_quiz_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Clôturer officiellement une séance de quiz en temps réel."""
    quiz_session = session.get(QuizSession, session_id)
    if not quiz_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Séance introuvable."
        )

    # Only the host professor can end the session
    if quiz_session.prof_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non autorisé à clôturer cette séance."
        )

    quiz_session.statut = "terminee"
    session.add(quiz_session)
    session.commit()
    session.refresh(quiz_session)

    # Notify all room participants via Socket.io
    room = f"session_{quiz_session.code_session}"
    await sio.emit("session:ended", {"session_id": session_id}, room=room)

    logger.info(f"Quiz session {quiz_session.code_session} ended by professor {current_user.id}")
    return {"status": "success", "message": "Séance clôturée avec succès."}
