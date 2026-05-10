"""
Centralised application configuration.

All environment-driven settings live here so the rest of the codebase
imports from a single source of truth instead of calling os.getenv ad-hoc.
"""

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
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    for d in (settings.upload_dir, settings.static_dir, settings.data_dir, settings.generated_dir):
        d.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
