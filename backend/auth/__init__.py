"""Auth package: password hashing, JWT handling, FastAPI dependencies, routes."""

from .dependencies import get_current_user, get_optional_user
from .jwt_handler import create_access_token, decode_access_token
from .password import hash_password, verify_password
from .routes import router as auth_router

__all__ = [
    "auth_router",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_optional_user",
    "hash_password",
    "verify_password",
]
