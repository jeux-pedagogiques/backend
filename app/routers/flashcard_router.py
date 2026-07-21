"""Router for flashcard generation and spaced repetition review."""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select, func, and_

from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.module_analysis import ModuleAnalysis
from app.models.flashcard import FlashcardSet, Flashcard, FlashcardReview
from app.schemas.flashcard import (
    GenerateFlashcardRequest,
    FlashcardSetResponse,
    FlashcardResponse,
    FlashcardSessionResponse,
    ReviewFlashcardRequest,
    FlashcardReviewResponse,
    FlashcardStatsResponse,
)

router = APIRouter(prefix="/api/flashcards", tags=["flashcards"])


@router.post("/generate", response_model=FlashcardSetResponse)
async def generate_flashcards(
    data: GenerateFlashcardRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Generate a flashcard set from a module analysis using Gemini AI."""
    from app.services.flashcard_service import generate_flashcards as generate_flashcards_ai

    entry = session.get(ModuleAnalysis, data.module_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Fiche module introuvable.")
    if entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé à accéder à cette fiche module.")
    if not entry.learning_outcomes:
        raise HTTPException(status_code=400, detail="La fiche module ne contient pas d'acquis d'apprentissage.")

    try:
        flashcard_data = await generate_flashcards_ai(
            learning_outcomes=entry.learning_outcomes,
            key_concepts=entry.key_concepts or [],
            keywords=entry.keywords or [],
            nb_cartes=data.nb_cartes,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la génération des flashcards : {str(e)}")

    flashcard_set = FlashcardSet(
        user_id=current_user.id,
        module_id=data.module_id,
        titre=flashcard_data.get("titre", "Flashcards"),
        nb_cartes=len(flashcard_data.get("cartes", [])),
    )
    session.add(flashcard_set)
    session.flush()

    for i, carte in enumerate(flashcard_data.get("cartes", [])):
        card = Flashcard(
            set_id=flashcard_set.id,
            recto=carte.get("recto", ""),
            verso=carte.get("verso", ""),
            aa_source=carte.get("aa_source", ""),
            niveau_bloom=carte.get("niveau_bloom", ""),
            ordre=i + 1,
        )
        session.add(card)

    # Register in the unified library catalogue
    from app.services.library_service import register_library_item
    niveaux = list({
        lo.get("bloom_level", "")
        for lo in entry.learning_outcomes
        if lo.get("bloom_level")
    })
    register_library_item(
        session,
        user_id=current_user.id,
        game_type="flashcards",
        game_id=flashcard_set.id,
        module_id=data.module_id,
        titre=flashcard_set.titre,
        niveaux_bloom=niveaux,
        concepts_cles=entry.key_concepts or [],
    )

    session.commit()
    session.refresh(flashcard_set)

    return FlashcardSetResponse(
        id=flashcard_set.id,
        module_id=flashcard_set.module_id,
        module_title=entry.module_title,
        titre=flashcard_set.titre,
        nb_cartes=flashcard_set.nb_cartes,
        created_at=flashcard_set.created_at,
    )


@router.get("/sets", response_model=list[FlashcardSetResponse])
async def list_sets(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """List all flashcard sets for the current user."""
    statement = (
        select(FlashcardSet)
        .where(FlashcardSet.user_id == current_user.id)
        .order_by(FlashcardSet.created_at.desc())
    )
    sets = session.exec(statement).all()

    result = []
    for fs in sets:
        module = session.get(ModuleAnalysis, fs.module_id)
        result.append(FlashcardSetResponse(
            id=fs.id,
            module_id=fs.module_id,
            module_title=module.module_title if module else None,
            titre=fs.titre,
            nb_cartes=fs.nb_cartes,
            created_at=fs.created_at,
        ))
    return result


@router.get("/{set_id}", response_model=FlashcardSessionResponse)
async def get_set(
    set_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Get a flashcard set with all its cards."""
    fs = session.get(FlashcardSet, set_id)
    if not fs or fs.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Jeu de flashcards introuvable.")

    cards = session.exec(
        select(Flashcard)
        .where(Flashcard.set_id == set_id)
        .order_by(Flashcard.ordre)
    ).all()

    module = session.get(ModuleAnalysis, fs.module_id)

    return FlashcardSessionResponse(
        set_id=fs.id,
        titre=fs.titre,
        module_title=module.module_title if module else None,
        cartes=[FlashcardResponse.model_validate(c) for c in cards],
        total_cartes=len(cards),
        cartes_a_revoir=0,
    )


@router.get("/{set_id}/session", response_model=FlashcardSessionResponse)
async def get_session_cards(
    set_id: int,
    participant_name: str = Query(..., min_length=1),
    nb_cartes: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Get cards ordered by spaced repetition priority for a participant."""
    fs = session.get(FlashcardSet, set_id)
    if not fs or fs.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Jeu de flashcards introuvable.")

    cards = session.exec(
        select(Flashcard).where(Flashcard.set_id == set_id)
    ).all()

    cutoff = datetime.utcnow() - timedelta(days=7)

    card_scores = []
    for card in cards:
        recent_mal_su = session.exec(
            select(func.count(FlashcardReview.id)).where(
                and_(
                    FlashcardReview.flashcard_id == card.id,
                    FlashcardReview.participant_name == participant_name,
                    FlashcardReview.statut == "mal_su",
                    FlashcardReview.review_date >= cutoff,
                )
            )
        ).one()

        total_reviews = session.exec(
            select(func.count(FlashcardReview.id)).where(
                and_(
                    FlashcardReview.flashcard_id == card.id,
                    FlashcardReview.participant_name == participant_name,
                )
            )
        ).one()

        never_reviewed = 1 if total_reviews == 0 else 0
        score = recent_mal_su * 10 + never_reviewed * 5
        card_scores.append((card, score))

    card_scores.sort(key=lambda x: x[1], reverse=True)
    sorted_cards = [c for c, _ in card_scores]

    if nb_cartes > 0:
        sorted_cards = sorted_cards[:nb_cartes]

    cartes_a_revoir = sum(1 for _, s in card_scores if s > 0)
    module = session.get(ModuleAnalysis, fs.module_id)

    return FlashcardSessionResponse(
        set_id=fs.id,
        titre=fs.titre,
        module_title=module.module_title if module else None,
        cartes=[FlashcardResponse.model_validate(c) for c in sorted_cards],
        total_cartes=len(cards),
        cartes_a_revoir=min(cartes_a_revoir, nb_cartes if nb_cartes > 0 else cartes_a_revoir),
    )


@router.post("/{card_id}/review", response_model=FlashcardReviewResponse)
async def review_card(
    card_id: int,
    data: ReviewFlashcardRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Record a bien_su / mal_su review for a flashcard."""
    if data.statut not in ("bien_su", "mal_su"):
        raise HTTPException(status_code=400, detail="Le statut doit être 'bien_su' ou 'mal_su'.")

    card = session.get(Flashcard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard introuvable.")

    fs = session.get(FlashcardSet, card.set_id)
    if not fs or fs.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé.")

    review = FlashcardReview(
        flashcard_id=card_id,
        participant_name=data.participant_name,
        statut=data.statut,
    )
    session.add(review)
    session.commit()
    session.refresh(review)

    return FlashcardReviewResponse(
        id=review.id,
        flashcard_id=review.flashcard_id,
        statut=review.statut,
        review_date=review.review_date,
    )


@router.get("/{set_id}/stats", response_model=FlashcardStatsResponse)
async def get_stats(
    set_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Get memorization stats for a flashcard set, aggregated by AA."""
    fs = session.get(FlashcardSet, set_id)
    if not fs or fs.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Jeu de flashcards introuvable.")

    cards = session.exec(
        select(Flashcard).where(Flashcard.set_id == set_id)
    ).all()

    total_reviews = 0
    bien_su_count = 0
    mal_su_count = 0
    aa_stats: dict[str, dict] = {}

    for card in cards:
        reviews = session.exec(
            select(FlashcardReview).where(FlashcardReview.flashcard_id == card.id)
        ).all()

        card_bien = sum(1 for r in reviews if r.statut == "bien_su")
        card_mal = sum(1 for r in reviews if r.statut == "mal_su")
        total_reviews += len(reviews)
        bien_su_count += card_bien
        mal_su_count += card_mal

        aa = card.aa_source
        if aa not in aa_stats:
            aa_stats[aa] = {"aa_source": aa, "total": 0, "bien_su": 0, "mal_su": 0}
        aa_stats[aa]["total"] += len(reviews)
        aa_stats[aa]["bien_su"] += card_bien
        aa_stats[aa]["mal_su"] += card_mal

    taux = (bien_su_count / total_reviews * 100) if total_reviews > 0 else 0.0

    stats_par_aa = []
    for aa_data in aa_stats.values():
        aa_total = aa_data["total"]
        aa_bien = aa_data["bien_su"]
        aa_data["taux"] = round(aa_bien / aa_total * 100, 1) if aa_total > 0 else 0.0
        stats_par_aa.append(aa_data)

    return FlashcardStatsResponse(
        set_id=set_id,
        total_reviews=total_reviews,
        bien_su_count=bien_su_count,
        mal_su_count=mal_su_count,
        taux_memorisation=round(taux, 1),
        stats_par_aa=stats_par_aa,
    )


@router.delete("/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_set(
    set_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Delete a flashcard set and all its cards/reviews."""
    fs = session.get(FlashcardSet, set_id)
    if not fs or fs.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Jeu de flashcards introuvable.")

    cards = session.exec(select(Flashcard).where(Flashcard.set_id == set_id)).all()
    for card in cards:
        reviews = session.exec(
            select(FlashcardReview).where(FlashcardReview.flashcard_id == card.id)
        ).all()
        for r in reviews:
            session.delete(r)
        session.delete(card)

    session.delete(fs)
    session.commit()
