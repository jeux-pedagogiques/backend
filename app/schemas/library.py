"""Pydantic schemas for the Library API."""

from datetime import datetime
from pydantic import BaseModel


class LibraryItemResponse(BaseModel):
    """Single library catalogue entry returned to the frontend."""

    id: int
    game_type: str
    game_id: int
    module_id: int | None = None
    module_title: str | None = None
    titre: str
    niveaux_bloom: list[str] = []
    concepts_cles: list[str] = []
    archived: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class LibraryListResponse(BaseModel):
    """Paginated list of library items."""

    items: list[LibraryItemResponse]
    total: int
    page: int
    page_size: int


class DuplicateRequest(BaseModel):
    """Body for POST /library/{game_type}/{game_id}/duplicate."""

    new_module_id: int | None = None


class RegenerateRequest(BaseModel):
    """Body for PATCH /library/{game_type}/{game_id}/regenerate."""

    consignes: str  # Free-text additional instructions


class ArchiveRequest(BaseModel):
    """Body for PATCH /library/{game_type}/{game_id}/archive."""

    archived: bool
