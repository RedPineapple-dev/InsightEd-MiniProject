"""
Centralised application configuration.

All environment-driven settings live here so the rest of the codebase
imports from a single source of truth instead of calling os.getenv ad-hoc.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # MongoDB
    mongodb_uri: str = Field(
        default="",
        description="MongoDB Atlas connection string. Empty string disables Mongo features.",
    )
    mongodb_db_name: str = Field(default="insighted")

    # JWT / Auth
    jwt_secret: str = Field(
        default="change-me-in-production-please-use-a-long-random-string",
        description="HMAC secret for signing access tokens.",
    )
    jwt_algorithm: str = Field(default="HS256")
    access_token_ttl_minutes: int = Field(default=60 * 24 * 7)  # 1 week

    # AI
    # Single-key legacy field — still respected for backward compatibility.
    gemini_api_key: str = Field(default="")
    # Comma-separated list of keys for automatic rotation. Takes precedence
    # over ``gemini_api_key`` when populated.
    gemini_api_keys: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")
    # Max retries per LLM call across the key pool. With N keys and R retries
    # we attempt up to min(R, N) distinct keys before giving up.
    gemini_max_retries: int = Field(default=4)
    # Seconds a key stays on cooldown after a quota/rate failure before it's
    # eligible for rotation again.
    gemini_key_cooldown: int = Field(default=300)

    # Recommendations
    youtube_api_key: str = Field(default="")

    # CORS
    allowed_origins: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]
    )

    # Storage
    upload_dir: Path = Field(default=BASE_DIR / "uploads")
    static_dir: Path = Field(default=BASE_DIR / "static")
    data_dir: Path = Field(default=BASE_DIR / "data")
    generated_dir: Path = Field(default=BASE_DIR / "generated")

    @property
    def mongodb_enabled(self) -> bool:
        return bool(self.mongodb_uri.strip())

    @property
    def gemini_keys(self) -> List[str]:
        """Effective list of Gemini API keys, in priority order.

        Three accepted shapes (merged in this order, duplicates removed):

          1. ``GEMINI_API_KEY_1`` … ``GEMINI_API_KEY_N`` — one key per line.
             Most readable when you have many keys. Numbering can start at 1
             and skip gaps; ordering is numeric.
          2. ``GEMINI_API_KEYS`` — single comma-separated list.
          3. ``GEMINI_API_KEY``  — legacy single-key field.

        Whitespace-only and obviously-placeholder values are dropped.
        """
        seen: set[str] = set()
        out: List[str] = []

        def _push(raw: str) -> None:
            v = (raw or "").strip()
            # Skip empty values and common placeholders so the manager isn't
            # initialised with "PASTE_KEY_HERE" style strings.
            if not v or v.lower().startswith(("paste", "your-", "key", "<")):
                return
            if v in seen:
                return
            seen.add(v)
            out.append(v)

        # 1. Numbered slots — scan a generous range so users can paste up
        #    to dozens of keys without changing this code.
        for i in range(1, 51):
            _push(os.getenv(f"GEMINI_API_KEY_{i}", ""))

        # 2. CSV form
        for k in (self.gemini_api_keys or "").split(","):
            _push(k)

        # 3. Legacy single key
        _push(self.gemini_api_key)

        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    for d in (settings.upload_dir, settings.static_dir, settings.data_dir, settings.generated_dir):
        d.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
