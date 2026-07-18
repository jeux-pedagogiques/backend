from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship

class QuizSession(SQLModel, table=True):
    """Represents a live pedagogical quiz session."""
    __tablename__ = "quiz_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    prof_id: int = Field(foreign_key="users.id")
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", nullable=True)
    code_session: str = Field(unique=True, index=True, max_length=50)
    statut: str = Field(default="en_attente") # "en_attente", "en_cours", "terminee"
    mode: str = Field(default="formatif") # "formatif" | "competitif"
    current_question_id: Optional[str] = Field(default=None, nullable=True) # Track active question ID
    current_question_start: Optional[datetime] = Field(default=None, nullable=True) # Start time for latency check
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    participants: list["QuizParticipant"] = Relationship(back_populates="session", cascade_delete=True)


class QuizParticipant(SQLModel, table=True):
    """Represents a participant (student) in a live quiz session."""
    __tablename__ = "quiz_participants"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="quiz_sessions.id", index=True)
    pseudo: str = Field(max_length=100)
    socket_id: Optional[str] = Field(default=None, max_length=100, nullable=True)
    score_total: int = Field(default=0)
    is_active: bool = Field(default=True) # Handles client disconnects
    joined_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    session: QuizSession = Relationship(back_populates="participants")
    attempts: list["QuizAttempt"] = Relationship(back_populates="participant", cascade_delete=True)


class QuizAttempt(SQLModel, table=True):
    """Represents a single answer submitted by a participant for a question."""
    __tablename__ = "quiz_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    participant_id: int = Field(foreign_key="quiz_participants.id", index=True)
    question_id: str = Field(max_length=100)
    reponse_donnee: str = Field(max_length=255)
    est_correcte: bool
    temps_reponse_ms: int
    points_obtenus: int
    submitted_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    participant: QuizParticipant = Relationship(back_populates="attempts")
