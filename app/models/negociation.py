"""Models for Simulation de Négociation (Negotiation Simulation Game)."""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class Negociation(SQLModel, table=True):
    """Represents a Negotiation Simulation scenario generated from a module analysis."""

    __tablename__ = "negociations"

    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", index=True, nullable=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    titre: str = Field(max_length=255)
    contexte_scenario: str = Field(sa_column=Column(Text))

    # JSON Fields
    # personnages: list of dicts [{"nom_personnage": "...", "role_description": "...", "objectifs_secrets": "...", "arguments_cles": [...], "lignes_rouges_et_compromis": "..."}]
    personnages: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # points_passage: list of dicts [{"etape": 1, "temps_pourcentage": 25, "titre": "...", "instruction": "..."}]
    points_passage: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # criteres_debriefing: list of dicts [{"nom_critere": "...", "description": "...", "questions_reflexion": [...]}]
    criteres_debriefing: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    groupes: list["GroupeNegociation"] = Relationship(back_populates="negociation", cascade_delete=True)


class GroupeNegociation(SQLModel, table=True):
    """Negotiation team / group created during a live session."""

    __tablename__ = "groupe_negociations"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True)
    negociation_id: int = Field(foreign_key="negociations.id", index=True)
    nom_groupe: str = Field(max_length=255)
    statut: str = Field(default="en_cours")  # "en_cours", "accord_trouve", "pas_d_accord", "terminee"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    negociation: Negociation = Relationship(back_populates="groupes")
    assignations: list["AssignationPersonnage"] = Relationship(back_populates="groupe", cascade_delete=True)
    accord: Optional["AccordFinal"] = Relationship(back_populates="groupe", cascade_delete=True)


class AssignationPersonnage(SQLModel, table=True):
    """Individual character assignment for a participant in a negotiation group."""

    __tablename__ = "assignation_personnages"

    id: Optional[int] = Field(default=None, primary_key=True)
    groupe_negociation_id: int = Field(foreign_key="groupe_negociations.id", index=True)
    participant_id: str = Field(max_length=255, index=True)  # socket_id or participant identifier
    nom_personnage: str = Field(max_length=255)
    participant_pseudo: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    groupe: GroupeNegociation = Relationship(back_populates="assignations")


class AccordFinal(SQLModel, table=True):
    """Final agreement outcome recorded for a negotiation group."""

    __tablename__ = "accord_finaux"

    id: Optional[int] = Field(default=None, primary_key=True)
    groupe_negociation_id: int = Field(foreign_key="groupe_negociations.id", unique=True, index=True)
    resume_accord: str = Field(sa_column=Column(Text))
    participant_redacteur_id: str = Field(max_length=255)
    statut_accord: str = Field(default="conclu")  # "conclu", "echec_negociation"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    groupe: GroupeNegociation = Relationship(back_populates="accord")
