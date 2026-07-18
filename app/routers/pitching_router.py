"""Router for Pitching Challenge CRUD."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.pitching import PitchingSession, PitchingTeam, PitchingVote, PitchingFeedback
from app.models.module_analysis import ModuleAnalysis
from app.services.pitching_challenge_service import generate_pitching_challenge

router = APIRouter(prefix="/api/pitching", tags=["pitching"])


# --- Schemas ---

class GeneratePitchingRequest(BaseModel):
    module_id: int
    nb_equipes: int = 4
    duree_preparation: int = 10
    duree_pitch: int = 3
    duree_feedback: int = 5


class CreatePitchingSessionRequest(BaseModel):
    titre: str
    description: str | None = None
    module_id: int | None = None
    mode: str = "individuel"


class CreateTeamRequest(BaseModel):
    nom: str
    auteur_username: str | None = None


class CastVoteRequest(BaseModel):
    team_id: int
    voter_username: str
    voter_user_id: int | None = None
    score: int
    criteria_scores: dict[str, int] | None = None


class SubmitFeedbackRequest(BaseModel):
    author_username: str
    author_user_id: int | None = None
    texte: str
    team_id: int | None = None


# --- Endpoints ---

@router.post("/generate")
async def generate_challenge(
    data: GeneratePitchingRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    module = session.get(ModuleAnalysis, data.module_id)
    if not module or module.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Module introuvable")

    if not module.learning_outcomes:
        raise HTTPException(
            status_code=400,
            detail="Ce module n'a pas d'acquis d'apprentissage. Veuillez d'abord analyser une fiche module."
        )

    try:
        result = await generate_pitching_challenge(
            learning_outcomes=module.learning_outcomes,
            key_concepts=module.key_concepts or [],
            keywords=module.keywords or [],
            nb_equipes=data.nb_equipes,
            duree_preparation=data.duree_preparation,
            duree_pitch=data.duree_pitch,
            duree_feedback=data.duree_feedback,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération du pitching : {str(e)}")

    return {
        "module_id": module.id,
        "module_title": module.module_title,
        **result,
    }


@router.post("/sessions")
def create_session(
    data: CreatePitchingSessionRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    ps = PitchingSession(
        prof_id=current_user.id,
        module_id=data.module_id,
        titre=data.titre,
        description=data.description,
        mode=data.mode,
        statut="en_attente",
    )
    session.add(ps)
    session.commit()
    session.refresh(ps)
    return {"id": ps.id, "titre": ps.titre, "statut": ps.statut}


@router.post("/sessions/{session_id}/teams")
def add_team(
    session_id: int,
    data: CreateTeamRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    ps = session.get(PitchingSession, session_id)
    if not ps or ps.prof_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session introuvable")

    team = PitchingTeam(session_id=session_id, nom=data.nom, auteur_username=data.auteur_username)
    session.add(team)
    session.commit()
    session.refresh(team)
    return {"id": team.id, "nom": team.nom}


@router.post("/sessions/{session_id}/votes")
def cast_vote(
    session_id: int,
    data: CastVoteRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    ps = session.get(PitchingSession, session_id)
    if not ps:
        raise HTTPException(status_code=404, detail="Session introuvable")

    vote = PitchingVote(
        session_id=session_id,
        team_id=data.team_id,
        voter_username=data.voter_username,
        voter_user_id=data.voter_user_id,
        score=data.score,
        criteria_scores=data.criteria_scores,
    )
    session.add(vote)
    session.commit()
    session.refresh(vote)
    return {"id": vote.id, "score": vote.score}


@router.post("/sessions/{session_id}/feedbacks")
def submit_feedback(
    session_id: int,
    data: SubmitFeedbackRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    ps = session.get(PitchingSession, session_id)
    if not ps:
        raise HTTPException(status_code=404, detail="Session introuvable")

    fb = PitchingFeedback(
        session_id=session_id,
        team_id=data.team_id,
        author_username=data.author_username,
        author_user_id=data.author_user_id,
        texte=data.texte,
    )
    session.add(fb)
    session.commit()
    session.refresh(fb)
    return {"id": fb.id}


@router.get("/sessions")
def list_sessions(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    sessions = session.exec(
        select(PitchingSession).where(PitchingSession.prof_id == current_user.id)
    ).all()
    return [
        {"id": s.id, "titre": s.titre, "statut": s.statut, "mode": s.mode, "created_at": s.created_at.isoformat()}
        for s in sessions
    ]
