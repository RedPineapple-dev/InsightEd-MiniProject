"""User account models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from .common import TimestampedModel, utcnow


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class User(TimestampedModel):
    """Document stored in MongoDB.users."""

    name: str
    email: EmailStr
    password_hash: str
    last_login_at: Optional[datetime] = None
    avatar_url: Optional[str] = None
    role: str = Field(default="student")  # student | educator | admin


class UserPublic(BaseModel):
    """Safe view exposed via API — no password hash."""

    id: str
    name: str
    email: EmailStr
    role: str = "student"
    avatar_url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: Optional[datetime] = None
