"""Pydantic schemas for Storytelling Collaboratif."""

from typing import Optional, Any
from pydantic import BaseModel


class GenerateStorytellingRequest(BaseModel):
    module_id: int
    nb_etapes: Optional[int] = 4
    duree_minutes: Optional[int] = 20
    difficulte_creative: Optional[str] = "standard"
    model: Optional[str] = None


class StorytellingContributionRequest(BaseModel):
    participant_id: str
    pseudo: str
    etape_index: int
    texte_contribution: str
    mots_cles_utilises: Optional[list[str]] = []
    groupe_id: Optional[int] = None


class SubmitStoryRequest(BaseModel):
    groupe_id: Optional[int] = None
    nom_auteur_ou_groupe: Optional[str] = "Équipe"
    texte_complet: str


class EvaluateStoryRequest(BaseModel):
    texte_complet: str
    mots_cles_obligatoires: Optional[list[str]] = None
    model: Optional[str] = None
