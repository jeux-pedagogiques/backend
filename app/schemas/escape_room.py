from datetime import datetime
from pydantic import BaseModel


class EnigmeSchema(BaseModel):
    """Schema for a single escape room puzzle."""
    id: str
    ordre: int
    aa_source: str
    niveau_bloom: int
    enonce: str
    type_enigme: str  # "code" | "question" | "manipulation" | "association"
    solution: str
    indice_optionnel: str
    penalite_indice: int
    code_deverrouillage_suivant: str


class GrilleEvaluationSchema(BaseModel):
    """Schema for the evaluation grid."""
    criteres: list[str]
    bareme_temps: str


class EscapeRoomData(BaseModel):
    """Full escape room data structure returned by AI."""
    titre_escape_room: str
    scenario_intro: str
    enigmes: list[EnigmeSchema]
    resolution_finale: str
    duree_estimee_minutes: int
    fiche_animateur: str
    fiche_participant: str
    grille_evaluation: GrilleEvaluationSchema


class GenerateEscapeRoomRequest(BaseModel):
    """Request body for generating an escape room."""
    analysis_id: int | None = None
    nb_enigmes: int = 5
    difficulte: str = "moyen"  # "facile" | "moyen" | "difficile"
    mode: str = "collaboratif"  # "collaboratif" | "competitif"
    duree_totale: int = 45
    nb_equipes: int = 3
    model: str | None = None


class EscapeRoomResponse(BaseModel):
    """Response for a saved escape room."""
    id: int
    user_id: int
    analysis_id: int | None = None
    titre_escape_room: str
    scenario_intro: str
    duree_estimee_minutes: int
    nb_enigmes: int
    difficulte: str
    mode: str
    module_title: str | None = None
    escape_room_data: dict
    created_at: datetime

    model_config = {"from_attributes": True}
