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
    SX_DEFAULT_SOURCE_ID: str = Field(default="default")
    SX_SCHEDULERX_ENV: Path | None = Field(default=Path("../SchedulerX/backend/pipeline/.env"))
    SX_PROFILE_INDEX: int = Field(default=1)
    # Runtime backend strategy:
    # - SQLITE: use local sqlite DB directly (default, current behavior)
    # - POSTGRES_MIRROR: read from selected PostgreSQL profile and mirror rows into sqlite
    #   so plugin/API contracts remain unchanged.
    SX_DB_BACKEND_MODE: str = Field(default="SQLITE")
    SX_DB_BACKEND_SYNC_TTL_SEC: int = Field(default=120)
    SX_PIPELINE_DB_MODE: str = Field(default="LOCAL")
    SX_PIPELINE_DB_PROFILE: str | None = Field(default=None)
    SX_PIPELINE_DATABASE_URL: str | None = Field(default=None)
    # PostgreSQL primary runtime (new architecture)
    SX_POSTGRES_DSN: str | None = Field(default=None)
    SX_POSTGRES_ADMIN_DSN: str | None = Field(default=None)
    SX_POSTGRES_SCHEMA_PREFIX: str = Field(default="sx")
    SX_POSTGRES_REGISTRY_TABLE: str = Field(default="sx_source_registry")
    # Safety guard for unified schema naming (e.g., sx_p01_*):
    # when enabled, prevent cross-profile writes if source/profile/schema indexes differ.
    SX_SCHEMA_INDEX_GUARD: bool = Field(default=True)

    # Import behavior safety:
    # when enabled, primary table inserts use ON CONFLICT DO NOTHING and explicit updates
    # are only performed when a row is already known and changed.
    SX_IDEMPOTENT_MAIN_INSERTS: bool = Field(default=True)

    # API logging (diagnostic; stored outside vault)
    SX_API_LOG_DIR: Path = Field(default=Path("_logs"))
    SX_API_LOG_LEVEL: str = Field(default="INFO")
    # If enabled, logs every request (can be noisy with the Obsidian plugin).
    SX_API_LOG_ACCESS: bool = Field(default=False)
    # Timed rotation retention count (days). Old log files are auto-deleted.
    SX_API_LOG_BACKUP_COUNT: int = Field(default=14)

    # Strict API routing safety:
    # - Require callers to explicitly send source_id (header/query) rather than silently
    #   falling back to the default source.
    SX_API_REQUIRE_EXPLICIT_SOURCE: bool = Field(default=True)
    # - Require X-SX-Profile-Index to match source_id trailing index (assets_2 -> 2)
    #   when both are available.
    SX_API_ENFORCE_PROFILE_SOURCE_MATCH: bool = Field(default=True)

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

    # Cloudflare R2 Settings
    SX_R2_ACCOUNT_ID: str | None = Field(default=None)
    SX_R2_ACCESS_KEY_ID: str | None = Field(default=None)
    SX_R2_SECRET_ACCESS_KEY: str | None = Field(default=None)
    SX_R2_BUCKET_NAME: str | None = Field(default=None)
    SX_R2_PUBLIC_URL_PREFIX: str | None = Field(default=None)


def load_settings() -> Settings:
    s = Settings()
    if s.SX_MEDIA_VAULT is None:
        s.SX_MEDIA_VAULT = s.VAULT_default
    if s.SX_MEDIA_DATA_DIR is None:
        s.SX_MEDIA_DATA_DIR = s.DATA_DIR
    # Ensure parent dir exists
    s.SX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return s
