"""User collection access."""

from datetime import datetime
from typing import Optional

from bson import ObjectId

from db import get_db
from models.common import utcnow
from models.user import User, UserPublic


def _to_public(doc: dict) -> UserPublic:
    return UserPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        email=doc["email"],
        role=doc.get("role", "student"),
        avatar_url=doc.get("avatar_url"),
        created_at=doc.get("created_at", utcnow()),
        last_login_at=doc.get("last_login_at"),
    )


class UserRepo:
    @staticmethod
    def _coll():
        return get_db().users

    @classmethod
    async def get_by_email(cls, email: str) -> Optional[dict]:
        return await cls._coll().find_one({"email": email.lower()})

    @classmethod
    async def get_by_id(cls, user_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(user_id):
            return None
        return await cls._coll().find_one({"_id": ObjectId(user_id)})

    @classmethod
    async def create(cls, name: str, email: str, password_hash: str, role: str = "student") -> UserPublic:
        now = utcnow()
        doc = {
            "name": name,
            "email": email.lower(),
            "password_hash": password_hash,
            "role": role,
            "avatar_url": None,
            "last_login_at": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await cls._coll().insert_one(doc)
        doc["_id"] = result.inserted_id
        return _to_public(doc)

    @classmethod
    async def touch_login(cls, user_id: str) -> None:
        await cls._coll().update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"last_login_at": utcnow(), "updated_at": utcnow()}},
        )

    @classmethod
    async def update_profile(cls, user_id: str, **fields) -> Optional[UserPublic]:
        allowed = {"name", "avatar_url", "role"}
        update = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not update:
            doc = await cls.get_by_id(user_id)
            return _to_public(doc) if doc else None
        update["updated_at"] = utcnow()
        await cls._coll().update_one({"_id": ObjectId(user_id)}, {"$set": update})
        doc = await cls.get_by_id(user_id)
        return _to_public(doc) if doc else None

    @classmethod
    def to_public(cls, doc: dict) -> UserPublic:
        return _to_public(doc)
