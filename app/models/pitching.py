from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class PitchingSession(SQLModel, table=True):
    """Represents a pitching challenge session where students present and vote."""

    __tablename__ = "pitching_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    prof_id: int = Field(foreign_key="users.id", index=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", nullable=True)
    titre: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    statut: str = Field(default="en_attente")  # "en_attente", "en_cours", "terminee"
    mode: str = Field(default="individuel")  # "individuel" | "equipe"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    teams: list["PitchingTeam"] = Relationship(back_populates="session", cascade_delete=True)
    votes: list["PitchingVote"] = Relationship(back_populates="session", cascade_delete=True)
    feedbacks: list["PitchingFeedback"] = Relationship(back_populates="session", cascade_delete=True)


class PitchingTeam(SQLModel, table=True):
    """A team or individual presenting in a pitching session."""

    __tablename__ = "pitching_teams"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="pitching_sessions.id", index=True)
    nom: str = Field(max_length=255)
    auteur_username: Optional[str] = Field(default=None, max_length=100)
    score_total: int = Field(default=0)
    rang: Optional[int] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    session: PitchingSession = Relationship(back_populates="teams")
    votes_received: list["PitchingVote"] = Relationship(back_populates="team", cascade_delete=True)


class PitchingVote(SQLModel, table=True):
    """A vote cast by a participant for a pitching team."""

    __tablename__ = "pitching_votes"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="pitching_sessions.id", index=True)
    team_id: int = Field(foreign_key="pitching_teams.id", index=True)
    voter_username: str = Field(max_length=100)
    voter_user_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    score: int = Field(default=0)  # 1-5 or similar
    criteria_scores: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # e.g. {"originalite": 4, "presentation": 5, "pertinence": 3}
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    session: PitchingSession = Relationship(back_populates="votes")
    team: PitchingTeam = Relationship(back_populates="votes_received")


class PitchingFeedback(SQLModel, table=True):
    """Free-text feedback left by participants on pitching sessions."""

    __tablename__ = "pitching_feedbacks"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="pitching_sessions.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="pitching_teams.id", nullable=True)
    author_username: str = Field(max_length=100)
    author_user_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    texte: str = Field(sa_column=Column(Text))
    sentiment: Optional[str] = Field(default=None, max_length=20)  # "positif", "neutre", "negatif"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    session: PitchingSession = Relationship(back_populates="feedbacks")
