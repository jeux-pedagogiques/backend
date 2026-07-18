from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Text, JSON


class EscapeRoom(SQLModel, table=True):
    """Stores generated escape rooms linked to a module analysis."""

    __tablename__ = "escape_rooms"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    analysis_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", nullable=True)

    titre_escape_room: str = Field(max_length=255)
    scenario_intro: str = Field(default="", sa_column=Column(Text))
    duree_estimee_minutes: int = Field(default=45)

    # Parameters used for generation
    nb_enigmes: int = Field(default=5)
    difficulte: str = Field(default="moyen")  # "facile" | "moyen" | "difficile"
    mode: str = Field(default="collaboratif")  # "collaboratif" | "competitif"

    # Full generated escape room data stored as JSON
    escape_room_data: dict[str, Any] = Field(default={}, sa_column=Column(JSON))

    # Optional: link to a module analysis for the learning outcomes source
    module_title: Optional[str] = Field(default=None, max_length=255)

    created_at: datetime = Field(default_factory=datetime.utcnow)
