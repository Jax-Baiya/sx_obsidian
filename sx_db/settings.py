from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the SQLite library + API.

    Values are loaded from environment variables and `.env`.

    Notes:
    - Keep the database OUTSIDE the vault for performance.
    - Use VAULT/VAULT_WINDOWS + PATH_STYLE to generate sxopen/sxreveal links.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    SX_DB_PATH: Path = Field(default=Path("data/sx_obsidian.db"))
    SX_DB_ENABLE_FTS: bool = Field(default=True)

    # API
    SX_API_HOST: str = Field(default="127.0.0.1")
    SX_API_PORT: int = Field(default=8123)
    SX_API_CORS_ALLOW_ALL: bool = Field(default=True)

    # API logging (diagnostic; stored outside vault)
    SX_API_LOG_DIR: Path = Field(default=Path("_logs"))
    SX_API_LOG_LEVEL: str = Field(default="INFO")
    # If enabled, logs every request (can be noisy with the Obsidian plugin).
    SX_API_LOG_ACCESS: bool = Field(default=False)
    # Timed rotation retention count (days). Old log files are auto-deleted.
    SX_API_LOG_BACKUP_COUNT: int = Field(default=14)

    # Import sources
    # Match existing generator conventions (these keys already exist in the repo's .env)
    CSV_consolidated_1: str | None = Field(default=None)
    CSV_authors_1: str | None = Field(default=None)
    CSV_bookmarks_1: str | None = Field(default=None)

    # Path/link formatting (reuse the generator's env conventions)
    VAULT_default: str | None = Field(default=None)
    VAULT_WINDOWS_default: str | None = Field(default=None)
    PATH_STYLE: str = Field(default="windows")
    DATA_DIR: str = Field(default="data")

    # Media serving (for plugin thumbnails/video preview)
    # Defaults assume API runs in WSL/Linux and can read VAULT_default paths.
    SX_MEDIA_VAULT: str | None = Field(default=None)
    SX_MEDIA_DATA_DIR: str | None = Field(default=None)
    SX_MEDIA_STYLE: str = Field(default="linux")

    # Notes
    SX_ACTIVE_NOTES_DIR: str = Field(default="_db/media_active")


def load_settings() -> Settings:
    s = Settings()
    if s.SX_MEDIA_VAULT is None:
        s.SX_MEDIA_VAULT = s.VAULT_default
    if s.SX_MEDIA_DATA_DIR is None:
        s.SX_MEDIA_DATA_DIR = s.DATA_DIR
    # Ensure parent dir exists
    s.SX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return s
