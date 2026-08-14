"""SQLModel models for the Débat Structuré (Structured Debate) game.

Un débat oppose deux camps fixes (Pour / Contre) autour d'une problématique
liée au cours. Chaque participant reçoit un rôle (avocat, avocat du diable,
modérateur, observateur-rapporteur). Les prises de parole sont chronométrées
et l'observateur collecte des notes. Une synthèse IA est générée à la fin.
"""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class Debat(SQLModel, table=True):
    """A structured debate generated from a module analysis."""

    __tablename__ = "debats"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", index=True, nullable=True)

    problematique: str = Field(sa_column=Column(Text))

    # Arguments initiaux générés par l'IA pour chaque camp (listes de chaînes)
    camp_pour: list[str] = Field(default=[], sa_column=Column(JSON))
    camp_contre: list[str] = Field(default=[], sa_column=Column(JSON))

    # Roles: [{"nom_role": "avocat", "description": "...", "missions": [...]}]
    roles: list[dict[str, Any]] = Field(default=[], sa_column=Column(JSON))

    # Questions de relance pour le modérateur
    questions_relance: list[str] = Field(default=[], sa_column=Column(JSON))

    statut: str = Field(default="en_attente")  # "en_attente" | "en_cours" | "terminee"

    # Synthèse finale générée par l'IA à la fin du débat
    synthese: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    participants: list["ParticipantDebat"] = Relationship(back_populates="debat", cascade_delete=True)
    interventions: list["PriseDeParole"] = Relationship(back_populates="debat", cascade_delete=True)
    notes: list["NoteObservateur"] = Relationship(back_populates="debat", cascade_delete=True)


class ParticipantDebat(SQLModel, table=True):
    """A participant registered in a debate session with a camp and a role."""

    __tablename__ = "participants_debat"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: Optional[int] = Field(default=None, index=True)  # session hôte (live/quiz) ou 0
    debat_id: int = Field(foreign_key="debats.id", index=True)
    participant_id: str = Field(max_length=100)  # socket sid / user id / pseudo
    pseudo: str = Field(max_length=255)
    camp: str = Field(default="neutre")  # "pour" | "contre" | "neutre"
    role: str = Field(default="participant")  # "avocat" | "avocat_du_diable" | "moderateur" | "observateur_rapporteur"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    debat: Debat = Relationship(back_populates="participants")


class PriseDeParole(SQLModel, table=True):
    """A recorded speech turn during the debate, with server-side timing."""

    __tablename__ = "prises_de_parole"

    id: Optional[int] = Field(default=None, primary_key=True)
    debat_id: int = Field(foreign_key="debats.id", index=True)
    participant_id: str = Field(max_length=100)
    pseudo: str = Field(max_length=255)
    camp: str = Field(default="neutre")  # "pour" | "contre" | "neutre"
    contenu: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    timestamp_debut: datetime = Field(default_factory=datetime.utcnow)
    timestamp_fin: Optional[datetime] = Field(default=None, nullable=True)
    duree_secondes: Optional[int] = Field(default=None, nullable=True)

    # Relationships
    debat: Debat = Relationship(back_populates="interventions")


class NoteObservateur(SQLModel, table=True):
    """A note written by the observer-rapporteur during the debate."""

    __tablename__ = "notes_observateur"

    id: Optional[int] = Field(default=None, primary_key=True)
    debat_id: int = Field(foreign_key="debats.id", index=True)
    participant_id: str = Field(max_length=100)  # observateur-rapporteur
    pseudo: str = Field(max_length=255)
    note_texte: str = Field(sa_column=Column(Text))
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    debat: Debat = Relationship(back_populates="notes")
