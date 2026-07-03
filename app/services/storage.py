import os
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings


def ensure_free_space(path: Path) -> None:
    settings = get_settings()
    path.mkdir(parents=True, exist_ok=True)
    free_mb = shutil.disk_usage(path).free // 1024 // 1024
    if free_mb < settings.min_free_disk_mb:
        raise RuntimeError("insufficient_disk_space")


def make_token() -> str:
    return secrets.token_urlsafe(32)


def expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=get_settings().download_link_ttl_seconds)


def safe_unlink(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
