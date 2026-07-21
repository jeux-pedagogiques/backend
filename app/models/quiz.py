"""Quiz model — dedicated table for generated quizzes."""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class Quiz(SQLModel, table=True):
    """
    Stores a generated quiz independently of ModuleAnalysis.quiz_data.
    This allows quizzes to be treated as first-class library items
    alongside EscapeRoom, FlashcardSet, PitchingSession, etc.
    """

    __tablename__ = "quizzes"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    module_id: Optional[int] = Field(
        default=None, foreign_key="module_analyses.id", index=True
    )

    titre: str = Field(max_length=255)
    nb_questions: int = Field(default=5)
    mode: str = Field(default="formatif", max_length=50)
    # "formatif" | "compétitif" | "collaboratif"

    # Full quiz payload from Gemini
    quiz_data: dict[str, Any] = Field(default={}, sa_column=Column(JSON))

    module_title: Optional[str] = Field(default=None, max_length=255)

    created_at: datetime = Field(default_factory=datetime.utcnow)
