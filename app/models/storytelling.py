"""SQLModel models for Storytelling Collaboratif (Collaborative Storytelling Workshop).

Bloom Taxonomy: N6 (Créer / Concevoir, Produire).
Students collaboratively craft a structured narrative anchored in course concepts,
guided by narrative arc steps, mandatory keywords, and assigned creative roles.
"""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class Storytelling(SQLModel, table=True):
    """A collaborative storytelling scenario generated from a module analysis."""

    __tablename__ = "storytellings"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", index=True, nullable=True)

    titre: str = Field(max_length=255)
    contexte_depart: str = Field(sa_column=Column(Text))

    # Mandatory concepts / keywords to mobilize in the story
    mots_cles_obligatoires: list[str] = Field(default=[], sa_column=Column(JSON))

    # Narrative arc stages: [{"etape": 1, "titre": "...", "description": "...", "consigne": "...", "temps_minutes": 3}]
    etapes_narratives: list[dict[str, Any]] = Field(default=[], sa_column=Column(JSON))

    # Assigned narrative roles: [{"nom_role": "...", "description": "...", "missions": [...]}]
    roles_narratifs: list[dict[str, Any]] = Field(default=[], sa_column=Column(JSON))

    # Pedagogical guidance
    fiche_animateur: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    fiche_participant: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Debriefing rubric: [{"critere": "...", "description": "...", "bareme": "..."}]
    criteres_evaluation: Optional[list[dict[str, Any]]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    groupes: list["StorytellingGroupe"] = Relationship(back_populates="storytelling", cascade_delete=True)
    contributions: list["StorytellingContribution"] = Relationship(back_populates="storytelling", cascade_delete=True)


class StorytellingGroupe(SQLModel, table=True):
    """A collaborative team / group formed during a live storytelling session."""

    __tablename__ = "storytelling_groupes"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True)
    storytelling_id: int = Field(foreign_key="storytellings.id", index=True)
    nom_groupe: str = Field(max_length=255)
    statut: str = Field(default="en_cours")  # "en_cours", "soumis", "terminee"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    storytelling: Storytelling = Relationship(back_populates="groupes")
    contributions: list["StorytellingContribution"] = Relationship(back_populates="groupe", cascade_delete=True)
    histoire_finale: Optional["StorytellingHistoireFinale"] = Relationship(back_populates="groupe", cascade_delete=True)


class StorytellingContribution(SQLModel, table=True):
    """An individual paragraph or contribution to an arc step by a student."""

    __tablename__ = "storytelling_contributions"

    id: Optional[int] = Field(default=None, primary_key=True)
    storytelling_id: int = Field(foreign_key="storytellings.id", index=True)
    groupe_id: Optional[int] = Field(default=None, foreign_key="storytelling_groupes.id", index=True, nullable=True)
    participant_id: str = Field(max_length=100)
    pseudo: str = Field(max_length=255)
    etape_index: int = Field(default=0)
    texte_contribution: str = Field(sa_column=Column(Text))
    mots_cles_utilises: list[str] = Field(default=[], sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    storytelling: Storytelling = Relationship(back_populates="contributions")
    groupe: Optional[StorytellingGroupe] = Relationship(back_populates="contributions")


class StorytellingHistoireFinale(SQLModel, table=True):
    """The completed consolidated story and AI debriefing evaluation."""

    __tablename__ = "storytelling_histoires_finales"

    id: Optional[int] = Field(default=None, primary_key=True)
    storytelling_id: int = Field(foreign_key="storytellings.id", index=True)
    groupe_id: Optional[int] = Field(default=None, foreign_key="storytelling_groupes.id", unique=True, index=True, nullable=True)
    nom_auteur_ou_groupe: str = Field(default="Équipe", max_length=255)
    texte_complet: str = Field(sa_column=Column(Text))
    note_ia_evaluation: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    submitted_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    groupe: Optional[StorytellingGroupe] = Relationship(back_populates="histoire_finale")
