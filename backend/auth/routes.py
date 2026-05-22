"""Auth routes: /auth/register, /auth/login, /auth/me, /auth/refresh."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from db import is_connected
from models.user import UserCreate, UserLogin, UserPublic
from repositories.users import UserRepo

from .dependencies import get_current_user
from .jwt_handler import create_access_token
from .password import hash_password, verify_password


router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None


def _require_db() -> None:
    if not is_connected():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication requires MongoDB. Configure MONGODB_URI in .env.",
        )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: UserCreate):
    _require_db()
    existing = await UserRepo.get_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await UserRepo.create(
        name=payload.name.strip(),
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    token = create_access_token(subject=user.id, extra_claims={"email": user.email})
    return TokenResponse(access_token=token, user=user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin):
    _require_db()
    user_doc = await UserRepo.get_by_email(payload.email)
    if not user_doc or not verify_password(payload.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await UserRepo.touch_login(str(user_doc["_id"]))
    user = UserRepo.to_public({**user_doc, "last_login_at": user_doc.get("last_login_at")})
    token = create_access_token(subject=user.id, extra_claims={"email": user.email})
    return TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=UserPublic)
async def me(current: UserPublic = Depends(get_current_user)):
    return current


@router.patch("/me", response_model=UserPublic)
async def update_me(
    payload: ProfileUpdate,
    current: UserPublic = Depends(get_current_user),
):
    updated = await UserRepo.update_profile(
        user_id=current.id,
        name=payload.name,
        avatar_url=payload.avatar_url,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated
