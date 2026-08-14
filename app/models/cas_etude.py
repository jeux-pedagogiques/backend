"""Models for Cas d'Étude Gamifié (Case Study Game)."""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class CasEtude(SQLModel, table=True):
    """Represents a gamified Case Study generated from a module."""

    __tablename__ = "cas_etudes"

    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", index=True, nullable=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    titre: str = Field(max_length=255)
    contexte_scenario: str = Field(sa_column=Column(Text))
    
    # JSON Fields
    # roles: list of dicts [{"nom_role": "Directeur Technique", "objectifs": "...", "infos_privees": "..."}]
    roles: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    
    # questions_decisions: list of dicts [{"id": "q1", "titre": "...", "contexte": "...", "impact": "..."}]
    questions_decisions: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    
    # grille_evaluation: dict or list of criteria [{"critere": "...", "poids": 1, "description": "..."}]
    grille_evaluation: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    
    format_restitution: str = Field(default="oral")  # "oral" | "ecrit"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    equipes: list["EquipeCasEtude"] = Relationship(back_populates="cas_etude", cascade_delete=True)


class EquipeCasEtude(SQLModel, table=True):
    """Team formed during a Case Study session."""

    __tablename__ = "equipe_cas_etudes"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True)
    cas_etude_id: int = Field(foreign_key="cas_etudes.id", index=True)
    nom_equipe: str = Field(max_length=255)
    statut: str = Field(default="en_attente")  # "en_attente", "en_analyse", "restitution_faite"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    cas_etude: CasEtude = Relationship(back_populates="equipes")
    role_assignments: list["RoleAssignment"] = Relationship(back_populates="equipe", cascade_delete=True)
    decisions: list["DecisionEquipe"] = Relationship(back_populates="equipe", cascade_delete=True)


class RoleAssignment(SQLModel, table=True):
    """Role assignment to a participant in a Case Study team."""

    __tablename__ = "role_assignments"

    id: Optional[int] = Field(default=None, primary_key=True)
    equipe_cas_etude_id: int = Field(foreign_key="equipe_cas_etudes.id", index=True)
    participant_id: str = Field(max_length=255, index=True)  # socket_id or participant unique identifier
    nom_role: str = Field(max_length=255)
    participant_pseudo: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    equipe: EquipeCasEtude = Relationship(back_populates="role_assignments")


class DecisionEquipe(SQLModel, table=True):
    """Team decision and justification for a specific question in a Case Study."""

    __tablename__ = "decision_equipes"

    id: Optional[int] = Field(default=None, primary_key=True)
    equipe_cas_etude_id: int = Field(foreign_key="equipe_cas_etudes.id", index=True)
    question_id: str = Field(max_length=255)
    decision_texte: str = Field(sa_column=Column(Text))
    justification_texte: str = Field(sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    equipe: EquipeCasEtude = Relationship(back_populates="decisions")
