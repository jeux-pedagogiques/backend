from datetime import datetime
from pydantic import BaseModel


class GenerateFlashcardRequest(BaseModel):
    """Request body for generating a flashcard set."""
    module_id: int
    nb_cartes: int = 20


class FlashcardSetResponse(BaseModel):
    """Response for a flashcard set."""
    id: int
    module_id: int
    module_title: str | None = None
    titre: str
    nb_cartes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class FlashcardResponse(BaseModel):
    """Response for a single flashcard."""
    id: int
    set_id: int
    recto: str
    verso: str
    aa_source: str
    niveau_bloom: str
    ordre: int

    model_config = {"from_attributes": True}


class FlashcardSessionResponse(BaseModel):
    """Response for a revision session with prioritized cards."""
    set_id: int
    titre: str
    module_title: str | None = None
    cartes: list[FlashcardResponse]
    total_cartes: int
    cartes_a_revoir: int


class ReviewFlashcardRequest(BaseModel):
    """Request body for reviewing a flashcard."""
    statut: str  # "bien_su" | "mal_su"
    participant_name: str


class FlashcardReviewResponse(BaseModel):
    """Response for a recorded review."""
    id: int
    flashcard_id: int
    statut: str
    review_date: datetime

    model_config = {"from_attributes": True}


class FlashcardStatsResponse(BaseModel):
    """Response for flashcard memorization statistics."""
    set_id: int
    total_reviews: int
    bien_su_count: int
    mal_su_count: int
    taux_memorisation: float
    stats_par_aa: list[dict]
