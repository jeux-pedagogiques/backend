"""Models for Atelier Feedback Pair module."""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class AtelierFeedback(SQLModel, table=True):
    """Represents an Atelier Feedback Pair configuration generated or created for a module."""

    __tablename__ = "atelier_feedbacks"

    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", nullable=True, index=True)
    titre: str = Field(max_length=255)
    criteres: Optional[dict[str, Any] | list[Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    structure_grille: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    anonyme: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    presentations: list["PresentationAtelier"] = Relationship(back_populates="atelier_feedback", cascade_delete=True)


class PresentationAtelier(SQLModel, table=True):
    """A presentation slot or group presenting work in an Atelier Feedback session."""

    __tablename__ = "presentation_ateliers"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: Optional[int] = Field(default=None, index=True, nullable=True)
    atelier_feedback_id: int = Field(foreign_key="atelier_feedbacks.id", index=True)
    participant_ou_groupe_id: str = Field(max_length=255)
    nom_presentateur: Optional[str] = Field(default=None, max_length=255)
    ordre_passage: int = Field(default=1)
    statut: str = Field(default="en_attente")  # "en_attente", "en_cours", "termine"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    atelier_feedback: AtelierFeedback = Relationship(back_populates="presentations")
    feedbacks_recus: list["FeedbackRecu"] = Relationship(back_populates="presentation", cascade_delete=True)


class FeedbackRecu(SQLModel, table=True):
    """A peer feedback evaluation form submitted for a presentation."""

    __tablename__ = "feedback_recus"

    id: Optional[int] = Field(default=None, primary_key=True)
    presentation_id: int = Field(foreign_key="presentation_ateliers.id", index=True)
    evaluateur_id: Optional[str] = Field(default=None, nullable=True, max_length=255)  # Nullable if anonymous
    notes_par_critere: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    points_positifs: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    axes_amelioration: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    note_synthese: Optional[float] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    presentation: PresentationAtelier = Relationship(back_populates="feedbacks_recus")
