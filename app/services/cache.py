from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def platform_from_url(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host.removeprefix("www.") or "unknown"


def cache_key(normalized_url: str, quality: str) -> str:
    return hashlib.sha256(f"{normalized_url}|{quality}".encode("utf-8")).hexdigest()


def local_cache_path(downloads_dir: Path, key: str, suffix: str = ".mp4") -> Path:
    return downloads_dir / "cache" / f"{key}{suffix}"
