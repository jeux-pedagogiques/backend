"""Router for shareable game URLs — create share links, public game access, and student results."""

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.game_share import GameShare, GameResult
from app.models.quiz import Quiz
from app.models.escape_room import EscapeRoom
from app.models.flashcard import FlashcardSet, Flashcard
from app.models.pitching import PitchingSession
from app.models.cas_etude import CasEtude
from app.models.mindmap import MindMap

router = APIRouter(prefix="/api/shares", tags=["shares"])

VALID_GAME_TYPES = {"quiz", "escape_room", "flashcards", "pitching", "cas_etude", "mindmap"}


# ─── Request / Response Schemas ──────────────────────────────────────

class CreateShareRequest(BaseModel):
    game_type: str
    game_id: int


class CreateShareResponse(BaseModel):
    share_token: str
    share_url: str


class SubmitResultRequest(BaseModel):
    student_name: str
    score: Optional[float] = None
    max_score: Optional[float] = None
    completion_time_seconds: Optional[int] = None
    result_data: Optional[dict[str, Any]] = None


# ─── Professor Endpoints (Auth Required) ─────────────────────────────

@router.post("", response_model=CreateShareResponse)
def create_share(
    req: CreateShareRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Professor creates a shareable link for a game."""
    if req.game_type not in VALID_GAME_TYPES:
        raise HTTPException(400, f"Invalid game_type. Must be one of: {VALID_GAME_TYPES}")

    # Verify the game exists and belongs to the current user
    game = _get_game_or_404(session, req.game_type, req.game_id, current_user.id)

    # Check if a share already exists for this game
    existing = session.exec(
        select(GameShare).where(
            GameShare.game_type == req.game_type,
            GameShare.game_id == req.game_id,
            GameShare.user_id == current_user.id,
            GameShare.is_active == True,
        )
    ).first()

    if existing:
        return CreateShareResponse(
            share_token=existing.share_token,
            share_url=f"/play/{req.game_type}/{existing.share_token}",
        )

    share = GameShare(
        game_type=req.game_type,
        game_id=req.game_id,
        user_id=current_user.id,
    )
    session.add(share)
    session.commit()
    session.refresh(share)

    return CreateShareResponse(
        share_token=share.share_token,
        share_url=f"/play/{req.game_type}/{share.share_token}",
    )


@router.get("/results/{game_type}/{game_id}")
def get_results(
    game_type: str,
    game_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Professor views all student results for a shared game."""
    shares = session.exec(
        select(GameShare).where(
            GameShare.game_type == game_type,
            GameShare.game_id == game_id,
            GameShare.user_id == current_user.id,
        )
    ).all()

    if not shares:
        return {"results": [], "total": 0}

    share_ids = [s.id for s in shares]
    results = session.exec(
        select(GameResult).where(GameResult.share_id.in_(share_ids)).order_by(GameResult.completed_at.desc())
    ).all()

    return {
        "results": [
            {
                "id": r.id,
                "student_name": r.student_name,
                "score": r.score,
                "max_score": r.max_score,
                "completion_time_seconds": r.completion_time_seconds,
                "result_data": r.result_data,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in results
        ],
        "total": len(results),
    }


class ClaimSubjectRequest(BaseModel):
    student_name: str
    subject_index: int
    subject_title: str


# ─── Public Endpoints (No Auth) ──────────────────────────────────────

@router.get("/{token}")
def get_shared_game(token: str, session: Session = Depends(get_session)):
    """Public — load game data for a shared token."""
    share = session.exec(
        select(GameShare).where(GameShare.share_token == token, GameShare.is_active == True)
    ).first()

    if not share:
        raise HTTPException(404, "Share link not found or expired")

    game_data, titre = _load_game_data(session, share.game_type, share.game_id)

    claimed_subjects = []
    if share.game_type == "pitching":
        results = session.exec(
            select(GameResult).where(GameResult.share_id == share.id)
        ).all()
        for r in results:
            if r.result_data and "claimed_subject_index" in r.result_data:
                claimed_subjects.append({
                    "subject_index": r.result_data["claimed_subject_index"],
                    "subject_title": r.result_data.get("claimed_subject_title", ""),
                    "student_name": r.student_name,
                })

    return {
        "game_type": share.game_type,
        "game_id": share.game_id,
        "titre": titre,
        "game_data": game_data,
        "claimed_subjects": claimed_subjects,
    }


@router.post("/{token}/claim-subject")
def claim_subject(
    token: str,
    req: ClaimSubjectRequest,
    session: Session = Depends(get_session),
):
    """Public — student claims a subject in pitching challenge."""
    share = session.exec(
        select(GameShare).where(GameShare.share_token == token, GameShare.is_active == True)
    ).first()

    if not share:
        raise HTTPException(404, "Share link not found or expired")

    if not req.student_name or not req.student_name.strip():
        raise HTTPException(400, "Student name is required")

    # Check if subject index is already claimed
    results = session.exec(
        select(GameResult).where(GameResult.share_id == share.id)
    ).all()

    for r in results:
        if r.result_data and r.result_data.get("claimed_subject_index") == req.subject_index:
            if r.student_name != req.student_name.strip():
                raise HTTPException(
                    400, f"Ce sujet a déjà été réservé par {r.student_name}."
                )

    # Record claim
    result = GameResult(
        share_id=share.id,
        student_name=req.student_name.strip(),
        score=0,
        max_score=5,
        completion_time_seconds=0,
        result_data={
            "claimed_subject_index": req.subject_index,
            "claimed_subject_title": req.subject_title,
        },
    )
    session.add(result)
    session.commit()

    return {
        "status": "success",
        "subject_index": req.subject_index,
        "claimed_by": req.student_name.strip(),
    }


@router.post("/{token}/results")
def submit_result(
    token: str,
    req: SubmitResultRequest,
    session: Session = Depends(get_session),
):
    """Public — student submits game results."""
    share = session.exec(
        select(GameShare).where(GameShare.share_token == token, GameShare.is_active == True)
    ).first()

    if not share:
        raise HTTPException(404, "Share link not found or expired")

    if not req.student_name or not req.student_name.strip():
        raise HTTPException(400, "Student name is required")

    result = GameResult(
        share_id=share.id,
        student_name=req.student_name.strip(),
        score=req.score,
        max_score=req.max_score,
        completion_time_seconds=req.completion_time_seconds,
        result_data=req.result_data,
    )
    session.add(result)
    session.commit()
    session.refresh(result)

    return {
        "id": result.id,
        "student_name": result.student_name,
        "score": result.score,
        "max_score": result.max_score,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
    }


# ─── Internal Helpers ─────────────────────────────────────────────────

def _get_game_or_404(session: Session, game_type: str, game_id: int, user_id: int):
    """Verify the game exists and belongs to the user."""
    model_map = {
        "quiz": (Quiz, "user_id"),
        "escape_room": (EscapeRoom, "user_id"),
        "flashcards": (FlashcardSet, "user_id"),
        "pitching": (PitchingSession, "prof_id"),
        "cas_etude": (CasEtude, "user_id"),
        "mindmap": (MindMap, "user_id"),
    }
    model_cls, owner_field = model_map[game_type]
    game = session.get(model_cls, game_id)
    if not game:
        raise HTTPException(404, f"{game_type} with id {game_id} not found")
    if getattr(game, owner_field) != user_id:
        raise HTTPException(403, "You don't own this game")
    return game


def _load_game_data(session: Session, game_type: str, game_id: int):
    """Load the full game data for public consumption."""
    if game_type == "quiz":
        quiz = session.get(Quiz, game_id)
        if not quiz:
            raise HTTPException(404, "Quiz not found")
        return quiz.quiz_data, quiz.titre

    elif game_type == "escape_room":
        room = session.get(EscapeRoom, game_id)
        if not room:
            raise HTTPException(404, "Escape room not found")
        return room.escape_room_data, room.titre_escape_room

    elif game_type == "flashcards":
        stmt = select(FlashcardSet).where(FlashcardSet.id == game_id).options(
            selectinload(FlashcardSet.cartes)
        )
        fset = session.exec(stmt).first()
        if not fset:
            raise HTTPException(404, "Flashcard set not found")
        cards = [
            {
                "id": c.id,
                "recto": c.recto,
                "verso": c.verso,
                "aa_source": c.aa_source,
                "niveau_bloom": c.niveau_bloom,
                "ordre": c.ordre,
            }
            for c in sorted(fset.cartes, key=lambda x: x.ordre)
        ]
        return {"cards": cards, "nb_cartes": fset.nb_cartes}, fset.titre

    elif game_type == "pitching":
        ps = session.get(PitchingSession, game_id)
        if not ps:
            raise HTTPException(404, "Pitching session not found")
        return {"description": ps.description, "mode": ps.mode}, ps.titre

    elif game_type == "cas_etude":
        cas = session.get(CasEtude, game_id)
        if not cas:
            raise HTTPException(404, "Cas d'étude not found")
        return {
            "contexte_scenario": cas.contexte_scenario,
            "roles": cas.roles,
            "questions_decisions": cas.questions_decisions,
            "grille_evaluation": cas.grille_evaluation,
            "format_restitution": cas.format_restitution
        }, cas.titre

    elif game_type == "mindmap":
        mindmap = session.get(MindMap, game_id)
        if not mindmap:
            raise HTTPException(404, "Mind Map not found")
        return {
            "concept_central": mindmap.concept_central,
            "branches_suggerees": mindmap.branches_suggerees
        }, f"Mind Map : {mindmap.concept_central}"

    raise HTTPException(400, "Unknown game type")
