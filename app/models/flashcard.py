from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text


class FlashcardSet(SQLModel, table=True):
    """A set of flashcards generated from a module analysis."""

    __tablename__ = "flashcard_sets"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    module_id: int = Field(foreign_key="module_analyses.id", index=True)
    titre: str = Field(max_length=255)
    nb_cartes: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    cartes: list["Flashcard"] = Relationship(back_populates="set", cascade_delete=True)


class Flashcard(SQLModel, table=True):
    """A single flashcard with recto (question) and verso (answer)."""

    __tablename__ = "flashcards"

    id: Optional[int] = Field(default=None, primary_key=True)
    set_id: int = Field(foreign_key="flashcard_sets.id", index=True)
    recto: str = Field(max_length=500)
    verso: str = Field(sa_column=Column(Text))
    aa_source: str = Field(max_length=100)
    niveau_bloom: str = Field(max_length=50)
    ordre: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    set: FlashcardSet = Relationship(back_populates="cartes")
    reviews: list["FlashcardReview"] = Relationship(back_populates="flashcard", cascade_delete=True)


class FlashcardReview(SQLModel, table=True):
    """A review record for a flashcard (bien_su / mal_su)."""

    __tablename__ = "flashcard_reviews"

    id: Optional[int] = Field(default=None, primary_key=True)
    flashcard_id: int = Field(foreign_key="flashcards.id", index=True)
    participant_name: str = Field(max_length=100)
    statut: str = Field(max_length=20)  # "bien_su" | "mal_su"
    review_date: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    flashcard: Flashcard = Relationship(back_populates="reviews")
