"""Models for Mind Map Collaboratif (Collaborative Mind Map Game)."""

from datetime import datetime
from typing import Optional, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Text, JSON


class MindMap(SQLModel, table=True):
    """Represents a collaborative Mind Map generated from a module."""

    __tablename__ = "mindmaps"

    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: Optional[int] = Field(default=None, foreign_key="module_analyses.id", index=True, nullable=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    concept_central: str = Field(max_length=255)
    
    # JSON Fields
    # branches_suggerees: list of dicts [{"titre": "...", "description": "...", "questions_guidantes": ["..."]}]
    branches_suggerees: Optional[Any] = Field(default=None, sa_column=Column(JSON, nullable=True))
    
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    nodes: list["MindMapNode"] = Relationship(back_populates="mindmap", cascade_delete=True)


class MindMapNode(SQLModel, table=True):
    """Represents a node added by students in a team's mind map."""

    __tablename__ = "mindmap_nodes"

    id: Optional[int] = Field(default=None, primary_key=True)
    mindmap_id: int = Field(foreign_key="mindmaps.id", index=True)
    equipe_id: int = Field(index=True, default=0)
    parent_node_id: Optional[int] = Field(default=None, foreign_key="mindmap_nodes.id", index=True, nullable=True)
    titre: str = Field(max_length=255)
    cree_par_participant_id: str = Field(max_length=255)
    ordre: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    mindmap: MindMap = Relationship(back_populates="nodes")
