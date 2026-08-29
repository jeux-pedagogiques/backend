from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Text


class User(SQLModel, table=True):
    """User account stored in the database."""

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    email: str = Field(index=True, unique=True, max_length=255)
    hashed_password: str
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    address: Optional[str] = Field(default=None, max_length=255)
    bio: Optional[str] = Field(default=None, max_length=500)
    avatar: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    role: str = Field(default="prof", max_length=20)


class RegistrationVerification(SQLModel, table=True):
    """Temporary storage for pending registration verification codes."""

    __tablename__ = "registration_verifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=255)
    username: str = Field(max_length=50)
    hashed_password: str
    role: str = Field(default="student", max_length=20)
    code: str = Field(max_length=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(default_factory=datetime.utcnow)

