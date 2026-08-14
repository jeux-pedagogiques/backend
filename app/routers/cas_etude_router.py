"""REST Router for Cas d'Étude Gamifiée."""

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from app.database import get_session
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis
from app.models.cas_etude import CasEtude, EquipeCasEtude, RoleAssignment, DecisionEquipe
from app.services.auth_service import get_current_user
from app.services.cas_etude_service import generate_cas_etude

router = APIRouter(prefix="/api/cas-etude", tags=["Cas d'Étude"])


class GenerateCasEtudeRequest(BaseModel):
    module_id: int
    nb_roles: Optional[int] = 3
    format_restitution: Optional[str] = "oral"
    model: Optional[str] = None


@router.post("/generate", response_model=dict)
async def generate_cas_etude_endpoint(
    req: GenerateCasEtudeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate a new Case Study using AI based on a module analysis."""
    module = session.get(ModuleAnalysis, req.module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module Analysis not found")

    outcomes = module.learning_outcomes or []
    outcomes_dict = []
    for o in outcomes:
        if isinstance(o, dict):
            outcomes_dict.append({
                "description": o.get("description", str(o)),
                "bloom_level": o.get("bloom_level", "comprendre")
            })
        else:
            outcomes_dict.append({
                "description": getattr(o, "description", str(o)),
                "bloom_level": getattr(o, "bloom_level", "comprendre")
            })

    generated = await generate_cas_etude(
        module_title=module.module_title,
        learning_outcomes=outcomes_dict,
        key_concepts=module.key_concepts or [],
        keywords=module.keywords or [],
        nb_roles=req.nb_roles or 3,
        format_restitution=req.format_restitution or "oral",
        model=req.model,
    )

    cas = CasEtude(
        module_id=module.id,
        user_id=current_user.id,
        titre=generated.get("titre", f"Étude de cas: {module.module_title}"),
        contexte_scenario=generated.get("contexte_scenario", ""),
        roles=generated.get("roles", []),
        questions_decisions=generated.get("questions_decisions", []),
        grille_evaluation=generated.get("grille_evaluation", []),
        format_restitution=generated.get("format_restitution", req.format_restitution or "oral")
    )
    session.add(cas)
    session.commit()
    session.refresh(cas)

    # Register item in global library catalogue
    try:
        from app.services.library_service import register_library_item
        register_library_item(
            session=session,
            user_id=current_user.id,
            game_type="cas_etude",
            game_id=cas.id,
            module_id=module.id,
            titre=cas.titre,
            niveaux_bloom=["analyser", "evaluer", "creer"],
            concepts_cles=module.key_concepts or []
        )
        session.commit()
    except Exception as e:
        print(f"Warning: could not register cas_etude in library: {e}")

    return {
        "id": cas.id,
        "module_id": cas.module_id,
        "titre": cas.titre,
        "contexte_scenario": cas.contexte_scenario,
        "roles": cas.roles,
        "questions_decisions": cas.questions_decisions,
        "grille_evaluation": cas.grille_evaluation,
        "format_restitution": cas.format_restitution,
        "created_at": cas.created_at.isoformat() if cas.created_at else None
    }


@router.get("/{session_id}/results")
def get_cas_etude_results(
    session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get all team decisions, role assignments and evaluation grid for a session."""
    equipes = session.exec(
        select(EquipeCasEtude).where(EquipeCasEtude.session_id == session_id)
    ).all()

    results = []
    cas_etude_info = None

    for eq in equipes:
        if not cas_etude_info and eq.cas_etude_id:
            cas = session.get(CasEtude, eq.cas_etude_id)
            if cas:
                cas_etude_info = {
                    "id": cas.id,
                    "titre": cas.titre,
                    "contexte_scenario": cas.contexte_scenario,
                    "grille_evaluation": cas.grille_evaluation,
                    "questions_decisions": cas.questions_decisions,
                }

        roles = session.exec(
            select(RoleAssignment).where(RoleAssignment.equipe_cas_etude_id == eq.id)
        ).all()

        decisions = session.exec(
            select(DecisionEquipe).where(DecisionEquipe.equipe_cas_etude_id == eq.id)
        ).all()

        results.append({
            "equipe_id": eq.id,
            "nom_equipe": eq.nom_equipe,
            "statut": eq.statut,
            "roles": [
                {
                    "participant_id": r.participant_id,
                    "participant_pseudo": r.participant_pseudo,
                    "nom_role": r.nom_role,
                }
                for r in roles
            ],
            "decisions": [
                {
                    "question_id": d.question_id,
                    "decision_texte": d.decision_texte,
                    "justification_texte": d.justification_texte,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in decisions
            ]
        })

    return {
        "session_id": session_id,
        "cas_etude": cas_etude_info,
        "equipes": results,
        "total_equipes": len(results)
    }


@router.get("/{id}")
def get_cas_etude_detail(
    id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get single Cas d'Étude details."""
    cas = session.get(CasEtude, id)
    if not cas:
        raise HTTPException(status_code=404, detail="Cas d'étude not found")

    return {
        "id": cas.id,
        "module_id": cas.module_id,
        "titre": cas.titre,
        "contexte_scenario": cas.contexte_scenario,
        "roles": cas.roles,
        "questions_decisions": cas.questions_decisions,
        "grille_evaluation": cas.grille_evaluation,
        "format_restitution": cas.format_restitution,
        "created_at": cas.created_at.isoformat() if cas.created_at else None
    }
