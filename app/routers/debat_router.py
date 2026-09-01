"""REST Router for Débat Structuré (Structured Debate)."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from app.database import get_session
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis
from app.models.debat import Debat, ParticipantDebat, PriseDeParole, NoteObservateur
from app.services.auth_service import get_current_user
from app.services.debat_service import generate_debat, generate_debat_synthese

router = APIRouter(prefix="/api/debat", tags=["Débat Structuré"])


class GenerateDebatRequest(BaseModel):
    module_id: int
    nb_arguments_par_camp: Optional[int] = 3
    duree_intervention_secondes: Optional[int] = 120
    model: Optional[str] = None


def _resolve_debat_by_session(
    session: Session,
    session_id: int,
    current_user: User,
) -> Debat:
    """Resolve the Debat linked to a session via ParticipantDebat + ownership check."""
    parts = session.exec(
        select(ParticipantDebat).where(ParticipantDebat.session_id == session_id)
    ).all()

    if not parts:
        raise HTTPException(status_code=404, detail="Aucun débat trouvé pour cette session.")

    debat = session.get(Debat, parts[0].debat_id)
    if not debat:
        raise HTTPException(status_code=404, detail="Débat introuvable.")

    owner_id = debat.user_id
    if owner_id is None and debat.module_id:
        module = session.get(ModuleAnalysis, debat.module_id)
        owner_id = module.user_id if module else None

    if owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé à accéder à ce débat.")

    return debat


@router.post("/generate", response_model=dict)
async def generate_debat_endpoint(
    req: GenerateDebatRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate a new structured debate using AI based on a module analysis."""
    module = session.get(ModuleAnalysis, req.module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable.")

    if not module.learning_outcomes:
        raise HTTPException(
            status_code=400,
            detail="Ce module n'a pas d'acquis d'apprentissage. Veuillez d'abord analyser une fiche module."
        )

    outcomes_dict = []
    for o in module.learning_outcomes or []:
        if isinstance(o, dict):
            outcomes_dict.append({
                "id": o.get("id"),
                "description": o.get("description", str(o)),
                "bloom_level": o.get("bloom_level", "comprendre"),
            })
        else:
            outcomes_dict.append({
                "id": getattr(o, "id", None),
                "description": getattr(o, "description", str(o)),
                "bloom_level": getattr(o, "bloom_level", "comprendre"),
            })

    try:
        generated = await generate_debat(
            module_title=module.module_title,
            learning_outcomes=outcomes_dict,
            key_concepts=module.key_concepts or [],
            keywords=module.keywords or [],
            nb_arguments_par_camp=req.nb_arguments_par_camp or 3,
            duree_intervention_secondes=req.duree_intervention_secondes or 120,
            model=req.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la génération du débat : {str(e)}")

    debat = Debat(
        user_id=current_user.id,
        module_id=module.id,
        problematique=generated.get("problematique", ""),
        camp_pour=generated.get("camp_pour", []),
        camp_contre=generated.get("camp_contre", []),
        roles=generated.get("roles", []),
        questions_relance=generated.get("questions_relance", []),
        statut="en_attente",
    )
    session.add(debat)
    session.commit()
    session.refresh(debat)

    # Register in global library catalogue
    try:
        from app.services.library_service import register_library_item

        register_library_item(
            session=session,
            user_id=current_user.id,
            game_type="debat",
            game_id=debat.id,
            module_id=module.id,
            titre=debat.problematique or f"Débat structuré {debat.id}",
            niveaux_bloom=[o.get("bloom_level", "comprendre") for o in outcomes_dict],
            concepts_cles=module.key_concepts or [],
        )
        session.commit()
    except Exception as e:
        print(f"Warning: could not register debat in library: {e}")

    return {
        "id": debat.id,
        "module_id": debat.module_id,
        "module_title": module.module_title,
        "problematique": debat.problematique,
        "camp_pour": debat.camp_pour,
        "camp_contre": debat.camp_contre,
        "roles": debat.roles,
        "questions_relance": debat.questions_relance,
        "duree_intervention_secondes": req.duree_intervention_secondes or 120,
        "created_at": debat.created_at.isoformat() if debat.created_at else None,
    }


@router.get("/{session_id}/synthese")
async def get_debat_synthese(
    session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the final AI synthesis of the debate for the given session."""
    debat = _resolve_debat_by_session(session, session_id, current_user)

    if debat.statut != "terminee":
        raise HTTPException(
            status_code=404,
            detail="Synthèse non disponible : le débat n'est pas encore terminé.",
        )

    if debat.synthese is None:
        # Régénération de sécurité si l'événement debat:end a échoué.
        interventions = session.exec(
            select(PriseDeParole)
            .where(PriseDeParole.debat_id == debat.id)
            .order_by(PriseDeParole.timestamp_debut)
        ).all()
        notes = session.exec(
            select(NoteObservateur).where(NoteObservateur.debat_id == debat.id)
        ).all()
        try:
            debat.synthese = await generate_debat_synthese(
                problematique=debat.problematique,
                interventions=[
                    {
                        "pseudo": i.pseudo,
                        "camp": i.camp,
                        "contenu": i.contenu,
                        "duree_secondes": i.duree_secondes,
                    }
                    for i in interventions
                ],
                notes=[n.note_texte for n in notes],
            )
            session.add(debat)
            session.commit()
        except RuntimeError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur lors de la génération de la synthèse : {str(e)}")

    return {
        "session_id": session_id,
        "debat_id": debat.id,
        "problematique": debat.problematique,
        "synthese": debat.synthese,
    }


@router.get("/{session_id}/notes")
async def get_debat_notes(
    session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all observer notes collected during the debate for the given session."""
    debat = _resolve_debat_by_session(session, session_id, current_user)

    notes = session.exec(
        select(NoteObservateur)
        .where(NoteObservateur.debat_id == debat.id)
        .order_by(NoteObservateur.timestamp)
    ).all()

    return {
        "session_id": session_id,
        "debat_id": debat.id,
        "problematique": debat.problematique,
        "notes": [
            {
                "id": n.id,
                "participant_id": n.participant_id,
                "pseudo": n.pseudo,
                "note_texte": n.note_texte,
                "timestamp": n.timestamp.isoformat() if n.timestamp else None,
            }
            for n in notes
        ],
        "total_notes": len(notes),
    }


@router.get("/{id}")
async def get_debat_detail(
    id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a single Debat details."""
    debat = session.get(Debat, id)
    if not debat or debat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Débat introuvable.")

    return {
        "id": debat.id,
        "module_id": debat.module_id,
        "problematique": debat.problematique,
        "camp_pour": debat.camp_pour,
        "camp_contre": debat.camp_contre,
        "roles": debat.roles,
        "questions_relance": debat.questions_relance,
        "statut": debat.statut,
        "created_at": debat.created_at.isoformat() if debat.created_at else None,
    }
