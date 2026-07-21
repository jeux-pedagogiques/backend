"""Library service — registration, duplication, and regeneration helpers."""

import copy
import json
import logging
from typing import Any

from sqlmodel import Session, select

from app.models.library_item import LibraryItem
from app.models.escape_room import EscapeRoom
from app.models.flashcard import FlashcardSet, Flashcard
from app.models.pitching import PitchingSession
from app.models.quiz import Quiz
from app.models.module_analysis import ModuleAnalysis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registration — called by each game router after generation
# ---------------------------------------------------------------------------

def register_library_item(
    session: Session,
    *,
    user_id: int,
    game_type: str,
    game_id: int,
    module_id: int | None = None,
    titre: str,
    niveaux_bloom: list[str] | None = None,
    concepts_cles: list[str] | None = None,
) -> LibraryItem:
    """Create a LibraryItem row for a newly generated game."""
    item = LibraryItem(
        user_id=user_id,
        game_type=game_type,
        game_id=game_id,
        module_id=module_id,
        titre=titre,
        niveaux_bloom=niveaux_bloom or [],
        concepts_cles=concepts_cles or [],
    )
    session.add(item)
    session.flush()  # so search_vector trigger fires
    return item


# ---------------------------------------------------------------------------
# Game type → table mapping
# ---------------------------------------------------------------------------

GAME_TYPE_MAP: dict[str, type] = {
    "escape_room": EscapeRoom,
    "flashcards": FlashcardSet,
    "pitching": PitchingSession,
    "quiz": Quiz,
}


def _get_game_or_404(session: Session, game_type: str, game_id: int):
    """Fetch the underlying game row or raise ValueError."""
    model_cls = GAME_TYPE_MAP.get(game_type)
    if model_cls is None:
        raise ValueError(f"Type de jeu inconnu : {game_type}")
    game = session.get(model_cls, game_id)
    if game is None:
        raise ValueError(f"{game_type} #{game_id} introuvable.")
    return game


def _get_title_field(game_type: str, game) -> str:
    """Extract the title from a game object depending on type."""
    title_map = {
        "escape_room": "titre_escape_room",
        "flashcards": "titre",
        "pitching": "titre",
        "quiz": "titre",
    }
    return getattr(game, title_map.get(game_type, "titre"), "Sans titre")


# ---------------------------------------------------------------------------
# Duplication
# ---------------------------------------------------------------------------

def duplicate_game(
    session: Session,
    *,
    game_type: str,
    game_id: int,
    user_id: int,
    new_module_id: int | None = None,
) -> tuple[Any, LibraryItem]:
    """Deep-copy a game and register the duplicate in the library."""

    original = _get_game_or_404(session, game_type, game_id)

    if game_type == "escape_room":
        dup = EscapeRoom(
            user_id=user_id,
            analysis_id=new_module_id or original.analysis_id,
            titre_escape_room=f"{original.titre_escape_room} (copie)",
            scenario_intro=original.scenario_intro,
            duree_estimee_minutes=original.duree_estimee_minutes,
            nb_enigmes=original.nb_enigmes,
            difficulte=original.difficulte,
            mode=original.mode,
            module_title=original.module_title,
            escape_room_data=copy.deepcopy(original.escape_room_data),
        )
        session.add(dup)
        session.flush()

    elif game_type == "flashcards":
        dup = FlashcardSet(
            user_id=user_id,
            module_id=new_module_id or original.module_id,
            titre=f"{original.titre} (copie)",
            nb_cartes=original.nb_cartes,
        )
        session.add(dup)
        session.flush()

        # Copy individual flashcards
        cards = session.exec(
            select(Flashcard).where(Flashcard.set_id == game_id).order_by(Flashcard.ordre)
        ).all()
        for card in cards:
            dup_card = Flashcard(
                set_id=dup.id,
                recto=card.recto,
                verso=card.verso,
                aa_source=card.aa_source,
                niveau_bloom=card.niveau_bloom,
                ordre=card.ordre,
            )
            session.add(dup_card)

    elif game_type == "pitching":
        dup = PitchingSession(
            prof_id=user_id,
            module_id=new_module_id or original.module_id,
            titre=f"{original.titre} (copie)",
            description=original.description,
            mode=original.mode,
            statut="en_attente",
        )
        session.add(dup)
        session.flush()

    elif game_type == "quiz":
        dup = Quiz(
            user_id=user_id,
            module_id=new_module_id or original.module_id,
            titre=f"{original.titre} (copie)",
            nb_questions=original.nb_questions,
            mode=original.mode,
            quiz_data=copy.deepcopy(original.quiz_data),
            module_title=original.module_title,
        )
        session.add(dup)
        session.flush()

    else:
        raise ValueError(f"Duplication non supportée pour le type : {game_type}")

    # Resolve module for concepts
    module_id_resolved = new_module_id
    if not module_id_resolved:
        if game_type == "escape_room":
            module_id_resolved = original.analysis_id
        else:
            module_id_resolved = getattr(original, "module_id", None)

    concepts = []
    niveaux = []
    if module_id_resolved:
        module = session.get(ModuleAnalysis, module_id_resolved)
        if module:
            concepts = module.key_concepts or []
            for lo in (module.learning_outcomes or []):
                bl = lo.get("bloom_level", "")
                if bl and bl not in niveaux:
                    niveaux.append(bl)

    lib_item = register_library_item(
        session,
        user_id=user_id,
        game_type=game_type,
        game_id=dup.id,
        module_id=module_id_resolved,
        titre=_get_title_field(game_type, dup),
        niveaux_bloom=niveaux,
        concepts_cles=concepts,
    )

    return dup, lib_item


# ---------------------------------------------------------------------------
# Regeneration (AI)
# ---------------------------------------------------------------------------

async def regenerate_game(
    session: Session,
    *,
    game_type: str,
    game_id: int,
    user_id: int,
    consignes: str,
) -> Any:
    """Re-generate game content using AI with additional instructions."""

    game = _get_game_or_404(session, game_type, game_id)

    # Resolve module for learning outcomes
    if game_type == "escape_room":
        module_id = game.analysis_id
    else:
        module_id = getattr(game, "module_id", None)

    module = session.get(ModuleAnalysis, module_id) if module_id else None
    learning_outcomes = module.learning_outcomes if module else []
    key_concepts = module.key_concepts if module else []
    keywords = module.keywords if module else []

    if game_type == "escape_room":
        from app.services.escape_room_service import generate_escape_room

        new_data = await generate_escape_room(
            learning_outcomes=learning_outcomes,
            key_concepts=key_concepts,
            keywords=keywords,
            nb_enigmes=game.nb_enigmes,
            difficulte=game.difficulte,
            mode=game.mode,
            duree_totale=game.duree_estimee_minutes,
            nb_equipes=3,
        )
        # Update in place
        game.titre_escape_room = new_data.get("titre_escape_room", game.titre_escape_room)
        game.scenario_intro = new_data.get("scenario_intro", game.scenario_intro)
        game.escape_room_data = new_data
        session.add(game)

    elif game_type == "flashcards":
        from app.services.flashcard_service import generate_flashcards

        new_data = await generate_flashcards(
            learning_outcomes=learning_outcomes,
            key_concepts=key_concepts,
            keywords=keywords,
            nb_cartes=game.nb_cartes,
        )
        # Delete old cards
        old_cards = session.exec(
            select(Flashcard).where(Flashcard.set_id == game_id)
        ).all()
        for c in old_cards:
            session.delete(c)
        session.flush()

        # Insert new cards
        game.titre = new_data.get("titre", game.titre)
        game.nb_cartes = len(new_data.get("cartes", []))
        session.add(game)
        session.flush()

        for i, carte in enumerate(new_data.get("cartes", [])):
            card = Flashcard(
                set_id=game.id,
                recto=carte.get("recto", ""),
                verso=carte.get("verso", ""),
                aa_source=carte.get("aa_source", ""),
                niveau_bloom=carte.get("niveau_bloom", ""),
                ordre=i + 1,
            )
            session.add(card)

    elif game_type == "pitching":
        from app.services.pitching_challenge_service import generate_pitching_challenge

        new_data = await generate_pitching_challenge(
            learning_outcomes=learning_outcomes,
            key_concepts=key_concepts,
            keywords=keywords,
            nb_equipes=4,
            duree_preparation=10,
            duree_pitch=3,
            duree_feedback=5,
        )
        game.titre = new_data.get("titre_challenge", game.titre)
        game.description = json.dumps(new_data, ensure_ascii=False)
        session.add(game)

    elif game_type == "quiz":
        from app.services.gemini_service import generate_quiz_from_outcomes

        new_data = await generate_quiz_from_outcomes(
            learning_outcomes=learning_outcomes,
            key_concepts=key_concepts,
            keywords=keywords,
            nb_questions=game.nb_questions,
            duree_par_question=30,
            mode=game.mode,
            question_types=["qcm", "vrai_faux"],
        )
        game.titre = new_data.get("titre_quiz", game.titre)
        game.quiz_data = new_data
        session.add(game)

    else:
        raise ValueError(f"Régénération non supportée pour le type : {game_type}")

    # Update the corresponding library item
    lib_item = session.exec(
        select(LibraryItem).where(
            LibraryItem.game_type == game_type,
            LibraryItem.game_id == game_id,
        )
    ).first()
    if lib_item:
        lib_item.titre = _get_title_field(game_type, game)
        session.add(lib_item)

    session.flush()
    return game
