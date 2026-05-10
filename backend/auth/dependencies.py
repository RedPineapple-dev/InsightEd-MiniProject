"""FastAPI dependencies for auth."""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from db import is_connected
from models.user import UserPublic
from repositories.users import UserRepo

from .jwt_handler import decode_access_token


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> UserPublic:
    """Hard-required auth — raises 401 if missing/invalid."""

    if not is_connected():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication requires MongoDB. Configure MONGODB_URI in .env.",
        )

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_doc = await UserRepo.get_by_id(payload["sub"])
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    return UserRepo.to_public(user_doc)


async def get_optional_user(
    authorization: Optional[str] = Header(default=None),
) -> Optional[UserPublic]:
    """Soft auth — returns None when missing/invalid instead of raising."""

    if not is_connected():
        return None
    token = _extract_bearer(authorization)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    user_doc = await UserRepo.get_by_id(payload["sub"])
    return UserRepo.to_public(user_doc) if user_doc else None
