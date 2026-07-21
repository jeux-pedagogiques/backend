"""LibraryItem model — unified catalogue entry for all game types."""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, UniqueConstraint, Text
from sqlalchemy.dialects.postgresql import TSVECTOR


class LibraryItem(SQLModel, table=True):
    """
    Central catalogue entry that references every generated game.
    Each game (Quiz, EscapeRoom, PitchingSession, FlashcardSet, …)
    gets one LibraryItem row created at generation time.
    """

    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint("game_type", "game_id", name="uq_library_game"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    # Logical polymorphic FK -----------------------------------------------
    game_type: str = Field(max_length=50, index=True)
    # "quiz" | "escape_room" | "pitching" | "flashcards" | …
    game_id: int = Field(index=True)

    # Denormalised metadata for fast filtering / display -------------------
    module_id: Optional[int] = Field(
        default=None, foreign_key="module_analyses.id", index=True
    )
    titre: str = Field(max_length=255)
    niveaux_bloom: list[str] = Field(default=[], sa_column=Column(JSON))
    concepts_cles: list[str] = Field(default=[], sa_column=Column(JSON))

    # Soft-delete ----------------------------------------------------------
    archived: bool = Field(default=False, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # PostgreSQL full-text search vector (populated by DB trigger) ---------
    search_vector: Optional[Any] = Field(
        default=None,
        sa_column=Column(TSVECTOR().with_variant(Text, "sqlite"), nullable=True),
    )
