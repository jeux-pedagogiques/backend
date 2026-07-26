import uuid
from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON


class GameShare(SQLModel, table=True):
    """A shareable link for a game, created by a professor."""
    __tablename__ = "game_shares"

    id: Optional[int] = Field(default=None, primary_key=True)
    share_token: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:12],
        unique=True, index=True, max_length=50
    )
    game_type: str = Field(max_length=50)  # "quiz" | "escape_room" | "flashcards" | "pitching"
    game_id: int = Field(index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    results: list["GameResult"] = Relationship(back_populates="share", cascade_delete=True)


class GameResult(SQLModel, table=True):
    """Stores a student's result for a shared game."""
    __tablename__ = "game_results"

    id: Optional[int] = Field(default=None, primary_key=True)
    share_id: int = Field(foreign_key="game_shares.id", index=True)
    student_name: str = Field(max_length=100)
    score: Optional[float] = Field(default=None)
    max_score: Optional[float] = Field(default=None)
    completion_time_seconds: Optional[int] = Field(default=None)
    result_data: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    completed_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    share: GameShare = Relationship(back_populates="results")
