from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(..., alias="BOT_TOKEN")
    bot_api_base_url: str | None = Field(default=None, alias="BOT_API_BASE_URL")
    public_base_url: str = Field(default="http://localhost", alias="PUBLIC_BASE_URL")
    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    admin_user_ids: set[int] = Field(default_factory=set, alias="ADMIN_USER_IDS")
    downloads_dir: Path = Field(default=Path("/data/downloads"), alias="DOWNLOADS_DIR")
    max_telegram_file_mb: int = Field(default=1900, alias="MAX_TELEGRAM_FILE_MB")
    download_link_ttl_seconds: int = Field(default=10800, alias="DOWNLOAD_LINK_TTL_SECONDS")
    cleanup_interval_seconds: int = Field(default=900, alias="CLEANUP_INTERVAL_SECONDS")
    min_free_disk_mb: int = Field(default=1024, alias="MIN_FREE_DISK_MB")
    rq_queue_name: str = Field(default="downloads", alias="RQ_QUEUE_NAME")

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admins(cls, value: str | set[int] | list[int]) -> set[int]:
        if isinstance(value, set):
            return value
        if isinstance(value, list):
            return {int(v) for v in value}
        if not value:
            return set()
        return {int(part.strip()) for part in value.split(",") if part.strip()}

    @property
    def telegram_file_limit_bytes(self) -> int:
        return self.max_telegram_file_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
