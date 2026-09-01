"""REST Router for Storytelling Collaboratif."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from app.database import get_session
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis
from app.models.storytelling import Storytelling, StorytellingGroupe, StorytellingContribution, StorytellingHistoireFinale
from app.schemas.storytelling import (
    GenerateStorytellingRequest,
    StorytellingContributionRequest,
    SubmitStoryRequest,
    EvaluateStoryRequest,
)
from app.services.auth_service import get_current_user
from app.services.storytelling_service import generate_storytelling, evaluate_storytelling
from app.services.library_service import register_library_item

router = APIRouter(prefix="/api/storytelling", tags=["Storytelling Collaboratif"])


@router.post("/generate", response_model=dict)
async def generate_storytelling_endpoint(
    req: GenerateStorytellingRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate a new Storytelling scenario using AI based on a module analysis."""
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
                "bloom_level": o.get("bloom_level", "creer"),
            })
        else:
            outcomes_dict.append({
                "id": getattr(o, "id", None),
                "description": getattr(o, "description", str(o)),
                "bloom_level": getattr(o, "bloom_level", "creer"),
            })

    try:
        generated = await generate_storytelling(
            module_title=module.module_title,
            learning_outcomes=outcomes_dict,
            key_concepts=module.key_concepts or [],
            keywords=module.keywords or [],
            nb_etapes=req.nb_etapes or 4,
            duree_minutes=req.duree_minutes or 20,
            difficulte_creative=req.difficulte_creative or "standard",
            model=req.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la génération du storytelling : {str(e)}")

    storytelling = Storytelling(
        user_id=current_user.id,
        module_id=module.id,
        titre=generated.get("titre", f"Histoire Collaborative - {module.module_title}"),
        contexte_depart=generated.get("contexte_depart", ""),
        mots_cles_obligatoires=generated.get("mots_cles_obligatoires", []),
        etapes_narratives=generated.get("etapes_narratives", []),
        roles_narratifs=generated.get("roles_narratifs", []),
        fiche_animateur=generated.get("fiche_animateur"),
        fiche_participant=generated.get("fiche_participant"),
        criteres_evaluation=generated.get("criteres_evaluation", []),
    )
    session.add(storytelling)
    session.commit()
    session.refresh(storytelling)

    # Register in unified library
    try:
        register_library_item(
            session=session,
            user_id=current_user.id,
            game_type="storytelling",
            game_id=storytelling.id,
            module_id=module.id,
            titre=storytelling.titre,
            niveaux_bloom=["creer", "appliquer", "analyser"],
            concepts_cles=storytelling.mots_cles_obligatoires or (module.key_concepts or []),
        )
        session.commit()
    except Exception:
        session.rollback()

    return storytelling.model_dump()


@router.get("/history", response_model=list[dict])
def list_user_storytellings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all Storytelling scenarios created by the current user."""
    stories = session.exec(
        select(Storytelling).where(
            Storytelling.user_id == current_user.id
        ).order_by(Storytelling.created_at.desc())
    ).all()
    return [s.model_dump() for s in stories]


@router.get("/{storytelling_id}", response_model=dict)
def get_storytelling(
    storytelling_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a Storytelling scenario by ID."""
    story = session.get(Storytelling, storytelling_id)
    if not story:
        raise HTTPException(status_code=404, detail="Scénario storytelling introuvable.")
    if story.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé.")
    return story.model_dump()


@router.delete("/{storytelling_id}")
def delete_storytelling(
    storytelling_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a Storytelling scenario by ID."""
    story = session.get(Storytelling, storytelling_id)
    if not story:
        raise HTTPException(status_code=404, detail="Scénario storytelling introuvable.")
    if story.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé.")
    session.delete(story)
    session.commit()
    return {"message": "Storytelling supprimé avec succès"}


@router.get("/module/{module_id}", response_model=list[dict])
def list_storytellings_by_module(
    module_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all Storytelling scenarios for a given module."""
    stories = session.exec(
        select(Storytelling).where(
            Storytelling.module_id == module_id,
            Storytelling.user_id == current_user.id
        ).order_by(Storytelling.created_at.desc())
    ).all()
    return [s.model_dump() for s in stories]


@router.post("/{storytelling_id}/contribute", response_model=dict)
def add_contribution(
    storytelling_id: int,
    req: StorytellingContributionRequest,
    session: Session = Depends(get_session),
):
    """Save an individual contribution to an arc step."""
    story = session.get(Storytelling, storytelling_id)
    if not story:
        raise HTTPException(status_code=404, detail="Storytelling introuvable.")

    contrib = StorytellingContribution(
        storytelling_id=storytelling_id,
        groupe_id=req.groupe_id,
        participant_id=req.participant_id,
        pseudo=req.pseudo,
        etape_index=req.etape_index,
        texte_contribution=req.texte_contribution,
        mots_cles_utilises=req.mots_cles_utilises or [],
    )
    session.add(contrib)
    session.commit()
    session.refresh(contrib)
    return contrib.model_dump()


@router.get("/{storytelling_id}/contributions", response_model=list[dict])
def list_contributions(
    storytelling_id: int,
    groupe_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """List all contributions for a storytelling game or group."""
    query = select(StorytellingContribution).where(
        StorytellingContribution.storytelling_id == storytelling_id
    )
    if groupe_id is not None:
        query = query.where(StorytellingContribution.groupe_id == groupe_id)
    query = query.order_by(StorytellingContribution.etape_index.asc(), StorytellingContribution.timestamp.asc())
    contribs = session.exec(query).all()
    return [c.model_dump() for c in contribs]


@router.post("/{storytelling_id}/evaluate", response_model=dict)
async def evaluate_story_endpoint(
    storytelling_id: int,
    req: EvaluateStoryRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Evaluate a completed collaborative story with AI."""
    story = session.get(Storytelling, storytelling_id)
    if not story:
        raise HTTPException(status_code=404, detail="Storytelling introuvable.")

    mots_cles = req.mots_cles_obligatoires or story.mots_cles_obligatoires or []
    try:
        evaluation = await evaluate_storytelling(
            texte_complet=req.texte_complet,
            mots_cles_obligatoires=mots_cles,
            model=req.model,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur d'évaluation IA : {str(e)}")

    return evaluation
