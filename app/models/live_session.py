from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class LiveSession(SQLModel, table=True):
    """Represents a live video session created by a professor."""

    __tablename__ = "live_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: str = Field(index=True, unique=True, max_length=50)
    name: str = Field(max_length=255)
    creator_id: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)
    is_locked: bool = Field(default=False)


class LiveSessionParticipant(SQLModel, table=True):
    """Tracks participants (logged-in students, professors, and guests) joining a live session."""

    __tablename__ = "live_session_participants"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key="live_sessions.room_id")
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    username: str = Field(max_length=100)
    role: str = Field(max_length=20)  # "prof", "student", "guest"
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    left_at: Optional[datetime] = Field(default=None, nullable=True)


class ScheduledMeeting(SQLModel, table=True):
    """Represents a scheduled video meeting created by a professor for the future."""

    __tablename__ = "scheduled_meetings"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    scheduled_time: datetime = Field(index=True)
    duration_minutes: int = Field(default=60)
    room_id: str = Field(max_length=50, unique=True)
    creator_id: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
