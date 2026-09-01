"""Router for Simulation de Négociation REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Optional, List

from app.database import get_session
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis
from app.models.negociation import Negociation, GroupeNegociation, AssignationPersonnage, AccordFinal
from app.models.quiz_session import QuizSession
from app.routers.auth_router import get_current_user
from app.services.negociation_service import generate_negociation

router = APIRouter(prefix="/api/negociation", tags=["negociation"])


class NegociationGenerateRequest(BaseModel):
    analysis_id: int
    nb_personnages: Optional[int] = 2
    model: Optional[str] = None


class AccordSubmitRequest(BaseModel):
    groupe_negociation_id: int
    resume_accord: str
    participant_redacteur_id: str
    statut_accord: Optional[str] = "conclu"


@router.post("/generate", response_model=dict)
async def create_negociation(
    req: NegociationGenerateRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate a Negotiation Simulation using Gemini AI based on module analysis."""
    analysis = db.get(ModuleAnalysis, req.analysis_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fiche module non trouvée.",
        )

    try:
        data = await generate_negociation(
            module_title=analysis.module_title,
            learning_outcomes=analysis.learning_outcomes or [],
            key_concepts=analysis.key_concepts or [],
            keywords=analysis.keywords or [],
            nb_personnages=req.nb_personnages or 2,
            model=req.model,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération de la négociation: {str(e)}",
        )

    negociation = Negociation(
        module_id=analysis.id,
        user_id=current_user.id,
        titre=data.get("titre", f"Négociation - {analysis.module_title}"),
        contexte_scenario=data.get("contexte_scenario", ""),
        personnages=data.get("personnages", []),
        points_passage=data.get("points_passage", []),
        criteres_debriefing=data.get("criteres_debriefing", []),
    )

    db.add(negociation)
    db.commit()
    db.refresh(negociation)

    # Register in unified library
    try:
        from app.services.library_service import register_library_item
        register_library_item(
            session=db,
            user_id=current_user.id,
            game_type="negociation",
            game_id=negociation.id,
            module_id=negociation.module_id,
            titre=negociation.titre,
            niveaux_bloom=["analyser", "evaluer"],
            concepts_cles=analysis.key_concepts or []
        )
        db.commit()
    except Exception:
        pass

    return {
        "id": negociation.id,
        "module_id": negociation.module_id,
        "titre": negociation.titre,
        "contexte_scenario": negociation.contexte_scenario,
        "personnages": negociation.personnages,
        "points_passage": negociation.points_passage,
        "criteres_debriefing": negociation.criteres_debriefing,
        "created_at": negociation.created_at.isoformat(),
    }


@router.get("/history", response_model=List[dict])
def get_negociation_history(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieve history of negotiation simulations created by current user."""
    statement = (
        select(Negociation)
        .where(Negociation.user_id == current_user.id)
        .order_by(Negociation.created_at.desc())
    )
    results = db.exec(statement).all()

    return [
        {
            "id": n.id,
            "module_id": n.module_id,
            "titre": n.titre,
            "contexte_scenario": n.contexte_scenario,
            "personnages_count": len(n.personnages or []),
            "created_at": n.created_at.isoformat(),
        }
        for n in results
    ]


@router.get("/{negociation_id}", response_model=dict)
def get_negociation_by_id(
    negociation_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a specific negotiation simulation by ID."""
    negociation = db.get(Negociation, negociation_id)
    if not negociation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulation de négociation non trouvée.",
        )

    return {
        "id": negociation.id,
        "module_id": negociation.module_id,
        "titre": negociation.titre,
        "contexte_scenario": negociation.contexte_scenario,
        "personnages": negociation.personnages,
        "points_passage": negociation.points_passage,
        "criteres_debriefing": negociation.criteres_debriefing,
        "created_at": negociation.created_at.isoformat(),
    }


@router.get("/results/{session_id}", response_model=dict)
def get_session_negociation_results(
    session_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all negotiation agreements and debriefing strategy comparisons for a live session."""
    session_obj = db.get(QuizSession, session_id)
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session live non trouvée.",
        )

    groupes = db.exec(
        select(GroupeNegociation).where(GroupeNegociation.session_id == session_id)
    ).all()

    group_results = []
    for g in groupes:
        assignations = db.exec(
            select(AssignationPersonnage).where(AssignationPersonnage.groupe_negociation_id == g.id)
        ).all()
        accord = db.exec(
            select(AccordFinal).where(AccordFinal.groupe_negociation_id == g.id)
        ).first()

        group_results.append({
            "groupe_id": g.id,
            "nom_groupe": g.nom_groupe,
            "statut": g.statut,
            "participants": [
                {
                    "participant_id": a.participant_id,
                    "nom_personnage": a.nom_personnage,
                    "pseudo": a.participant_pseudo,
                }
                for a in assignations
            ],
            "accord": {
                "id": accord.id if accord else None,
                "resume_accord": accord.resume_accord if accord else "Aucun accord formalisé",
                "participant_redacteur_id": accord.participant_redacteur_id if accord else None,
                "statut_accord": accord.statut_accord if accord else "echec_negociation",
                "created_at": accord.created_at.isoformat() if accord else None,
            } if accord else None,
        })

    return {
        "session_id": session_id,
        "code_session": session_obj.code_session,
        "total_groupes": len(groupes),
        "groupes": group_results,
    }
