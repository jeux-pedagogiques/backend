from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Text, JSON


class ModuleAnalysis(SQLModel, table=True):
    """Stores the history of analyzed module fiches and their extracted outcomes."""

    __tablename__ = "module_analyses"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    module_title: str = Field(max_length=255)
    module_summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    original_content: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Structured AI outputs stored as JSON lists/objects
    learning_outcomes: list[dict[str, Any]] = Field(default=[], sa_column=Column(JSON))
    key_concepts: list[str] = Field(default=[], sa_column=Column(JSON))
    keywords: list[str] = Field(default=[], sa_column=Column(JSON))
    central_notions: list[str] = Field(default=[], sa_column=Column(JSON))

    estimated_duration: Optional[str] = Field(default=None, max_length=100)
    target_audience: Optional[str] = Field(default=None, max_length=255)

    # Cached generated quiz data to avoid re-generating
    quiz_data: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(default_factory=datetime.utcnow)
