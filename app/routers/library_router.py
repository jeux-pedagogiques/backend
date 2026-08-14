"""Router for the unified game library — list, detail, duplicate, regenerate, archive."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from sqlalchemy import cast, String

from app.database import get_session
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.library_item import LibraryItem
from app.models.module_analysis import ModuleAnalysis
from app.models.flashcard import Flashcard
from app.schemas.library import (
    LibraryItemResponse,
    LibraryListResponse,
    DuplicateRequest,
    RegenerateRequest,
    ArchiveRequest,
)
from app.services.library_service import (
    duplicate_game,
    regenerate_game,
    _get_game_or_404,
)

router = APIRouter(prefix="/api/library", tags=["library"])


# ---------------------------------------------------------------------------
# GET /library — paginated, filtered, full-text search
# ---------------------------------------------------------------------------

@router.get("", response_model=LibraryListResponse)
async def list_library(
    module_id: int | None = Query(default=None),
    bloom_level: list[str] | None = Query(default=None),
    game_type: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    archived: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """List library items with combined filters, FTS and pagination."""

    # Auto-sync missing CasEtude & Quiz items into LibraryItem
    try:
        from app.models.cas_etude import CasEtude
        from app.models.quiz import Quiz
        from app.services.library_service import register_library_item

        all_cases = session.exec(select(CasEtude).where(CasEtude.user_id == current_user.id)).all()
        for cas in all_cases:
            existing = session.exec(
                select(LibraryItem).where(
                    LibraryItem.game_type == "cas_etude",
                    LibraryItem.game_id == cas.id,
                    LibraryItem.user_id == current_user.id
                )
            ).first()
            if not existing:
                register_library_item(
                    session=session,
                    user_id=current_user.id,
                    game_type="cas_etude",
                    game_id=cas.id,
                    module_id=cas.module_id,
                    titre=cas.titre,
                    niveaux_bloom=["analyser", "evaluer", "creer"],
                    concepts_cles=[]
                )

        all_quizzes = session.exec(select(Quiz).where(Quiz.user_id == current_user.id)).all()
        for quiz in all_quizzes:
            existing = session.exec(
                select(LibraryItem).where(
                    LibraryItem.game_type == "quiz",
                    LibraryItem.game_id == quiz.id,
                    LibraryItem.user_id == current_user.id
                )
            ).first()
            if not existing:
                module = session.get(ModuleAnalysis, quiz.module_id) if quiz.module_id else None
                niveaux = list({
                    lo.get("bloom_level", "")
                    for lo in (module.learning_outcomes if module and module.learning_outcomes else [])
                    if lo.get("bloom_level")
                }) if module else ["memoriser", "comprendre"]
                register_library_item(
                    session=session,
                    user_id=current_user.id,
                    game_type="quiz",
                    game_id=quiz.id,
                    module_id=quiz.module_id,
                    titre=quiz.titre,
                    niveaux_bloom=niveaux,
                    concepts_cles=module.key_concepts if module and module.key_concepts else []
                )

        session.commit()
    except Exception:
        pass

    # Base query
    stmt = select(LibraryItem).where(
        LibraryItem.user_id == current_user.id,
        LibraryItem.archived == archived,
    )
    count_stmt = select(func.count(LibraryItem.id)).where(
        LibraryItem.user_id == current_user.id,
        LibraryItem.archived == archived,
    )

    # ---- Filters ----
    if module_id is not None:
        stmt = stmt.where(LibraryItem.module_id == module_id)
        count_stmt = count_stmt.where(LibraryItem.module_id == module_id)

    if game_type is not None:
        stmt = stmt.where(LibraryItem.game_type == game_type)
        count_stmt = count_stmt.where(LibraryItem.game_type == game_type)

    if bloom_level:
        # JSON array containment — at least one level matches
        for level in bloom_level:
            stmt = stmt.where(
                cast(LibraryItem.niveaux_bloom, String).contains(level)
            )
            count_stmt = count_stmt.where(
                cast(LibraryItem.niveaux_bloom, String).contains(level)
            )

    # ---- Full-text search ----
    if search:
        # Sanitise input for tsquery
        search_terms = " & ".join(
            term.strip() for term in search.split() if term.strip()
        )
        if search_terms:
            ts_query = func.to_tsquery("french", search_terms)
            stmt = stmt.where(LibraryItem.search_vector.op("@@")(ts_query))
            count_stmt = count_stmt.where(
                LibraryItem.search_vector.op("@@")(ts_query)
            )

    # ---- Sorting ----
    order_col = getattr(LibraryItem, sort_by, LibraryItem.created_at)
    if sort_order == "asc":
        stmt = stmt.order_by(order_col.asc())
    else:
        stmt = stmt.order_by(order_col.desc())

    # ---- Pagination ----
    total = session.exec(count_stmt).one()
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    items = session.exec(stmt).all()

    # Enrich with module_title
    result_items = []
    for item in items:
        module_title = None
        if item.module_id:
            module = session.get(ModuleAnalysis, item.module_id)
            module_title = module.module_title if module else None

        result_items.append(
            LibraryItemResponse(
                id=item.id,
                game_type=item.game_type,
                game_id=item.game_id,
                module_id=item.module_id,
                module_title=module_title,
                titre=item.titre,
                niveaux_bloom=item.niveaux_bloom or [],
                concepts_cles=item.concepts_cles or [],
                archived=item.archived,
                created_at=item.created_at,
            )
        )

    return LibraryListResponse(
        items=result_items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /library/{game_type}/{game_id} — full game detail
# ---------------------------------------------------------------------------

@router.get("/{game_type}/{game_id}")
async def get_game_detail(
    game_type: str,
    game_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Return full detail of a specific game from its native table."""
    try:
        game = _get_game_or_404(session, game_type, game_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Ownership check
    owner_field = "user_id" if hasattr(game, "user_id") else "prof_id"
    if getattr(game, owner_field) != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé.")

    # Build a response dict from the game model
    data = {}
    for key in game.__fields__:
        val = getattr(game, key)
        data[key] = val

    # For flashcards, include the cards
    if game_type == "flashcards":
        cards = session.exec(
            select(Flashcard).where(Flashcard.set_id == game_id).order_by(Flashcard.ordre)
        ).all()
        data["cartes"] = [
            {k: getattr(c, k) for k in c.__fields__}
            for c in cards
        ]
    elif game_type == "pitching":
        import json
        if game.description:
            try:
                data["pitching_data"] = json.loads(game.description)
            except Exception:
                pass

    # Add module info
    module_id = game.analysis_id if game_type == "escape_room" else getattr(game, "module_id", None)
    if module_id:
        module = session.get(ModuleAnalysis, module_id)
        data["module_title"] = module.module_title if module else None
    else:
        data["module_title"] = getattr(game, "module_title", None)

    data["game_type"] = game_type

    return data


# ---------------------------------------------------------------------------
# POST /library/{game_type}/{game_id}/duplicate
# ---------------------------------------------------------------------------

@router.post("/{game_type}/{game_id}/duplicate", response_model=LibraryItemResponse)
async def duplicate(
    game_type: str,
    game_id: int,
    body: DuplicateRequest | None = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Deep-copy a game and register the duplicate in the library."""
    try:
        game = _get_game_or_404(session, game_type, game_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Ownership check
    owner_field = "user_id" if hasattr(game, "user_id") else "prof_id"
    if getattr(game, owner_field) != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé.")

    try:
        dup, lib_item = duplicate_game(
            session,
            game_type=game_type,
            game_id=game_id,
            user_id=current_user.id,
            new_module_id=body.new_module_id if body else None,
        )
        session.commit()
        session.refresh(lib_item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Resolve module title
    module_title = None
    if lib_item.module_id:
        module = session.get(ModuleAnalysis, lib_item.module_id)
        module_title = module.module_title if module else None

    return LibraryItemResponse(
        id=lib_item.id,
        game_type=lib_item.game_type,
        game_id=lib_item.game_id,
        module_id=lib_item.module_id,
        module_title=module_title,
        titre=lib_item.titre,
        niveaux_bloom=lib_item.niveaux_bloom or [],
        concepts_cles=lib_item.concepts_cles or [],
        archived=lib_item.archived,
        created_at=lib_item.created_at,
    )


# ---------------------------------------------------------------------------
# PATCH /library/{game_type}/{game_id}/regenerate
# ---------------------------------------------------------------------------

@router.patch("/{game_type}/{game_id}/regenerate")
async def regenerate(
    game_type: str,
    game_id: int,
    body: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Re-generate game content using AI with additional instructions."""
    try:
        game = _get_game_or_404(session, game_type, game_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    owner_field = "user_id" if hasattr(game, "user_id") else "prof_id"
    if getattr(game, owner_field) != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé.")

    try:
        await regenerate_game(
            session,
            game_type=game_type,
            game_id=game_id,
            user_id=current_user.id,
            consignes=body.consignes,
        )
        session.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur lors de la régénération IA : {str(e)}",
        )

    return {"status": "ok", "message": "Jeu régénéré avec succès."}


# ---------------------------------------------------------------------------
# PATCH /library/{game_type}/{game_id}/archive
# ---------------------------------------------------------------------------

@router.patch("/{game_type}/{game_id}/archive", response_model=LibraryItemResponse)
async def archive(
    game_type: str,
    game_id: int,
    body: ArchiveRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Toggle the archived flag on a library item (soft delete)."""
    lib_item = session.exec(
        select(LibraryItem).where(
            LibraryItem.game_type == game_type,
            LibraryItem.game_id == game_id,
            LibraryItem.user_id == current_user.id,
        )
    ).first()

    if not lib_item:
        raise HTTPException(status_code=404, detail="Élément de bibliothèque introuvable.")

    lib_item.archived = body.archived
    session.add(lib_item)
    session.commit()
    session.refresh(lib_item)

    module_title = None
    if lib_item.module_id:
        module = session.get(ModuleAnalysis, lib_item.module_id)
        module_title = module.module_title if module else None

    return LibraryItemResponse(
        id=lib_item.id,
        game_type=lib_item.game_type,
        game_id=lib_item.game_id,
        module_id=lib_item.module_id,
        module_title=module_title,
        titre=lib_item.titre,
        niveaux_bloom=lib_item.niveaux_bloom or [],
        concepts_cles=lib_item.concepts_cles or [],
        archived=lib_item.archived,
        created_at=lib_item.created_at,
    )


# ---------------------------------------------------------------------------
# DELETE /library/{game_type}/{game_id} — delete game item
# ---------------------------------------------------------------------------

@router.delete("/{game_type}/{game_id}")
async def delete_game_item(
    game_type: str,
    game_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Permanently delete a game item from library and its underlying table."""
    lib_item = session.exec(
        select(LibraryItem).where(
            LibraryItem.game_type == game_type,
            LibraryItem.game_id == game_id,
            LibraryItem.user_id == current_user.id,
        )
    ).first()

    if lib_item:
        session.delete(lib_item)

    try:
        game = _get_game_or_404(session, game_type, game_id)
        owner_field = "user_id" if hasattr(game, "user_id") else "prof_id"
        if getattr(game, owner_field) == current_user.id:
            session.delete(game)
    except Exception:
        pass

    session.commit()
    return {"status": "ok", "message": "Jeu supprimé avec succès."}

