"""REST Router for Atelier Feedback Pair module."""

import random
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models.module_analysis import ModuleAnalysis
from app.models.atelier_feedback import AtelierFeedback, PresentationAtelier, FeedbackRecu
from app.services.atelier_feedback_service import generate_atelier_feedback, generate_consolidated_pdf

router = APIRouter(prefix="/atelier-feedback", tags=["Atelier Feedback Pair"])


class AtelierGenerateRequest(BaseModel):
    module_id: int
    titre: Optional[str] = None
    anonyme: bool = True
    nb_criteres: int = 4
    model: Optional[str] = None


@router.post("/generate", response_model=dict[str, Any])
async def generate_atelier_feedback_endpoint(
    req: AtelierGenerateRequest,
    session: Session = Depends(get_session)
):
    """
    Generates an Atelier Feedback grid via AI based on a module_id and persists it in the DB.
    """
    module = session.get(ModuleAnalysis, req.module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module non trouvé")

    learning_outcomes = module.learning_outcomes or []
    key_concepts = module.key_concepts or []
    keywords = module.keywords or []

    try:
        ai_data = await generate_atelier_feedback(
            learning_outcomes=learning_outcomes,
            key_concepts=key_concepts,
            keywords=keywords,
            nb_criteres=req.nb_criteres,
            model=req.model
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération IA: {str(e)}")

    titre_final = req.titre or ai_data.get("titre", "Atelier Feedback Pair")
    criteres_final = ai_data.get("criteres", [])
    structure_final = ai_data.get("structure_grille", {
        "note_min": 1,
        "note_max": 5,
        "sections": ["points_positifs", "axes_amelioration", "note_synthese"]
    })

    atelier = AtelierFeedback(
        module_id=module.id,
        titre=titre_final,
        criteres=criteres_final,
        structure_grille=structure_final,
        anonyme=req.anonyme
    )
    session.add(atelier)
    session.commit()
    session.refresh(atelier)

    return {
        "id": atelier.id,
        "module_id": atelier.module_id,
        "titre": atelier.titre,
        "criteres": atelier.criteres,
        "structure_grille": atelier.structure_grille,
        "anonyme": atelier.anonyme,
        "created_at": atelier.created_at.isoformat() if atelier.created_at else None
    }


@router.get("/history", response_model=list[dict[str, Any]])
def get_atelier_history(
    session: Session = Depends(get_session)
):
    """
    GET list of past created Atelier Feedback sessions.
    """
    statement = select(AtelierFeedback).order_by(AtelierFeedback.created_at.desc())
    ateliers = session.exec(statement).all()
    results = []
    for a in ateliers:
        module_title = "Module"
        key_concepts = []
        learning_outcomes = []
        if a.module_id:
            mod = session.get(ModuleAnalysis, a.module_id)
            if mod:
                module_title = mod.module_title
                key_concepts = mod.key_concepts or []
                learning_outcomes = mod.learning_outcomes or []

        results.append({
            "id": a.id,
            "module_id": a.module_id,
            "module_title": module_title,
            "titre": a.titre,
            "criteres": a.criteres or [],
            "criteres_count": len(a.criteres) if isinstance(a.criteres, list) else 0,
            "key_concepts": key_concepts,
            "learning_outcomes": learning_outcomes,
            "structure_grille": a.structure_grille,
            "anonyme": a.anonyme,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    return results


@router.get("/detail/{id}", response_model=dict[str, Any])
def get_atelier_detail(
    id: int,
    session: Session = Depends(get_session)
):
    """
    GET single Atelier Feedback by ID.
    """
    atelier = session.get(AtelierFeedback, id)
    if not atelier:
        raise HTTPException(status_code=404, detail="Atelier non trouvé")

    module_title = "Module"
    key_concepts = []
    learning_outcomes = []
    if atelier.module_id:
        mod = session.get(ModuleAnalysis, atelier.module_id)
        if mod:
            module_title = mod.module_title
            key_concepts = mod.key_concepts or []
            learning_outcomes = mod.learning_outcomes or []

    return {
        "id": atelier.id,
        "module_id": atelier.module_id,
        "module_title": module_title,
        "titre": atelier.titre,
        "criteres": atelier.criteres or [],
        "key_concepts": key_concepts,
        "learning_outcomes": learning_outcomes,
        "structure_grille": atelier.structure_grille,
        "anonyme": atelier.anonyme,
        "created_at": atelier.created_at.isoformat() if atelier.created_at else None,
    }


@router.delete("/{id}")
def delete_atelier(
    id: int,
    session: Session = Depends(get_session)
):
    """
    DELETE an Atelier Feedback by ID.
    """
    atelier = session.get(AtelierFeedback, id)
    if not atelier:
        raise HTTPException(status_code=404, detail="Atelier non trouvé")
    session.delete(atelier)
    session.commit()
    return {"status": "ok", "message": "Atelier supprimé avec succès"}


@router.get("/{session_id}/results/{presentation_id}", response_model=dict[str, Any])
def get_presentation_consolidated_results(
    session_id: int,
    presentation_id: int,
    session: Session = Depends(get_session)
):
    """
    GET consolidated feedback grid for a specific presenter/presentation.
    STRICT ANONYMITY REQUIREMENT:
    If anonyme=True, evaluateur_id is NEVER exposed and items/lists are randomly shuffled server-side.
    """
    presentation = session.get(PresentationAtelier, presentation_id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Présentation non trouvée")

    atelier = session.get(AtelierFeedback, presentation.atelier_feedback_id)
    is_anonyme = atelier.anonyme if atelier else True

    feedbacks = session.exec(
        select(FeedbackRecu).where(FeedbackRecu.presentation_id == presentation.id)
    ).all()

    total_feedbacks = len(feedbacks)
    notes_synthese = [f.note_synthese for f in feedbacks if f.note_synthese is not None]
    moyenne_note_synthese = (sum(notes_synthese) / len(notes_synthese)) if notes_synthese else None

    # Compute average per criterion
    criteres_totals: dict[str, list[float]] = {}
    for f in feedbacks:
        if f.notes_par_critere and isinstance(f.notes_par_critere, dict):
            for crit, val in f.notes_par_critere.items():
                if isinstance(val, (int, float)):
                    criteres_totals.setdefault(crit, []).append(float(val))

    moyennes_par_critere = {
        crit: (sum(vals) / len(vals))
        for crit, vals in criteres_totals.items()
    }

    points_positifs_list = [f.points_positifs for f in feedbacks if f.points_positifs]
    axes_amelioration_list = [f.axes_amelioration for f in feedbacks if f.axes_amelioration]

    feedbacks_detail = [
        {
            "id": f.id,
            "evaluateur_id": None if is_anonyme else f.evaluateur_id,
            "notes_par_critere": f.notes_par_critere,
            "points_positifs": f.points_positifs,
            "axes_amelioration": f.axes_amelioration,
            "note_synthese": f.note_synthese,
            "created_at": f.created_at.isoformat() if f.created_at else None
        }
        for f in feedbacks
    ]

    # STRICT ANONYMITY SHUFFLE REQUIREMENT:
    if is_anonyme:
        random.shuffle(feedbacks_detail)
        random.shuffle(points_positifs_list)
        random.shuffle(axes_amelioration_list)

    return {
        "session_id": session_id,
        "presentation_id": presentation.id,
        "participant_ou_groupe_id": presentation.participant_ou_groupe_id,
        "nom_presentateur": presentation.nom_presentateur or presentation.participant_ou_groupe_id,
        "atelier_titre": atelier.titre if atelier else "Atelier Feedback Pair",
        "anonyme": is_anonyme,
        "total_feedbacks": total_feedbacks,
        "moyenne_note_synthese": moyenne_note_synthese,
        "moyennes_par_critere": moyennes_par_critere,
        "compilation_points_positifs": points_positifs_list,
        "compilation_axes_amelioration": axes_amelioration_list,
        "feedbacks": feedbacks_detail
    }


@router.get("/{session_id}/export-pdf/{presentation_id}")
def export_consolidated_pdf(
    session_id: int,
    presentation_id: int,
    session: Session = Depends(get_session)
):
    """
    GET PDF export of the consolidated grid for a presenter.
    """
    presentation = session.get(PresentationAtelier, presentation_id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Présentation non trouvée")

    atelier = session.get(AtelierFeedback, presentation.atelier_feedback_id)
    if not atelier:
        raise HTTPException(status_code=404, detail="Atelier non trouvé")

    aggregated_data = get_presentation_consolidated_results(session_id, presentation_id, session)

    pdf_bytes = generate_consolidated_pdf(
        presentation_title=presentation.nom_presentateur or presentation.participant_ou_groupe_id,
        presenter_name=presentation.nom_presentateur or presentation.participant_ou_groupe_id,
        atelier_title=atelier.titre,
        aggregated_data=aggregated_data,
        is_anonyme=atelier.anonyme
    )

    filename = f"feedback_consolide_pres_{presentation_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
