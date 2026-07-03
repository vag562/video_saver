#!/usr/bin/env python3
"""Dependency-light smoke checks for project wiring.

This script intentionally uses only Python standard library modules so it can run
before third-party dependencies are installed. It validates syntax, expected files,
Docker Compose service names, key environment variables, and important code hooks.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FILES = [
    "Dockerfile",
    "docker-compose.yml",
    "nginx/default.conf",
    ".env.example",
    "README.md",
    "app/bot/main.py",
    "app/api/main.py",
    "app/worker/run.py",
    "app/worker/cleanup.py",
]
EXPECTED_SERVICES = {"postgres", "redis", "api", "bot", "worker", "cleanup", "nginx"}
EXPECTED_ENV = {
    "BOT_TOKEN",
    "BOT_API_BASE_URL",
    "PUBLIC_BASE_URL",
    "DATABASE_URL",
    "REDIS_URL",
    "ADMIN_USER_IDS",
    "DOWNLOADS_DIR",
    "MAX_TELEGRAM_FILE_MB",
    "DOWNLOAD_LINK_TTL_SECONDS",
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def check_files() -> None:
    missing = [path for path in EXPECTED_FILES if not (ROOT / path).exists()]
    if missing:
        fail(f"Missing expected files: {', '.join(missing)}")


def check_python_syntax() -> None:
    for path in sorted((ROOT / "app").rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def check_env_example() -> None:
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    present = {line.split("=", 1)[0] for line in env_text.splitlines() if line and not line.startswith("#")}
    missing = EXPECTED_ENV - present
    if missing:
        fail(f".env.example misses variables: {', '.join(sorted(missing))}")
    admin_line = next(
        (line for line in env_text.splitlines() if line.startswith("ADMIN_USER_IDS=")),
        None,
    )
    if admin_line is None:
        fail(".env.example misses ADMIN_USER_IDS")
    admin_value = admin_line.split("=", 1)[1]
    try:
        parsed_admins = json.loads(admin_value)
    except json.JSONDecodeError as exc:
        fail(f"ADMIN_USER_IDS must be a JSON list: {exc}")
    if not isinstance(parsed_admins, list):
        fail("ADMIN_USER_IDS must be a JSON list")


def check_compose_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    services_block = compose.split("services:", 1)[-1]
    services = set()
    for match in re.finditer(r"^  ([a-zA-Z0-9_-]+):$", services_block, flags=re.MULTILINE):
        name = match.group(1)
        if name not in {"postgres_data", "redis_data", "downloads"}:
            services.add(name)
    missing = EXPECTED_SERVICES - services
    if missing:
        fail(f"docker-compose.yml misses services: {', '.join(sorted(missing))}")
    for service in ["api", "bot", "worker", "cleanup"]:
        pattern = rf"^  {service}:\n(?P<body>(?:    .+\n|\n)+?)(?=^  [a-zA-Z0-9_-]+:|^volumes:|\Z)"
        match = re.search(pattern, compose, flags=re.MULTILINE)
        if not match or "env_file: .env" not in match.group("body"):
            fail(f"service {service} must use env_file: .env")


def check_nginx_proxy() -> None:
    nginx = (ROOT / "nginx/default.conf").read_text(encoding="utf-8")
    if "proxy_pass http://api:8000" not in nginx:
        fail("nginx must proxy to api:8000")


def check_dockerfile_tools() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    forbidden = ["apt-get update", "apt-get install"]
    for token in forbidden:
        if token in dockerfile:
            fail(f"Dockerfile must not use {token}")
    if "mwader/static-ffmpeg" not in dockerfile or "/ffprobe" not in dockerfile:
        fail("Dockerfile must copy ffmpeg and ffprobe from mwader/static-ffmpeg")
    if "denoland/deno:bin" not in dockerfile or "/deno" not in dockerfile:
        fail("Dockerfile must copy deno from denoland/deno:bin")


def check_important_hooks() -> None:
    factory = (ROOT / "app/bot/factory.py").read_text(encoding="utf-8")
    if "BOT_API_BASE_URL" not in (ROOT / "app/core/config.py").read_text(encoding="utf-8"):
        fail("settings must expose BOT_API_BASE_URL")
    if "TelegramAPIServer.from_base" not in factory or "is_local=True" not in factory:
        fail("bot factory must configure local Telegram Bot API when BOT_API_BASE_URL is set")
    worker = (ROOT / "app/worker/tasks.py").read_text(encoding="utf-8")
    media = (ROOT / "app/services/media.py").read_text(encoding="utf-8")
    ytdlp = (ROOT / "app/services/ytdlp.py").read_text(encoding="utf-8")
    if "telegram_file_limit_bytes" not in worker or "/downloads/" not in worker:
        fail("worker must enforce Telegram size limit and generate temporary links")
    if "ffprobe" not in media or "libx264" not in media or "aac" not in media:
        fail("media service must validate and convert files with ffprobe/ffmpeg")
    if "vcodec^=avc1" not in ytdlp or "acodec^=mp4a" not in ytdlp:
        fail("yt-dlp format selector must prefer H.264/AAC formats")
    api = (ROOT / "app/api/main.py").read_text(encoding="utf-8")
    if "expires_at" not in api:
        fail("download API must validate link expiration")


def main() -> int:
    check_files()
    check_python_syntax()
    check_env_example()
    check_compose_services()
    check_nginx_proxy()
    check_dockerfile_tools()
    check_important_hooks()
    print("Smoke check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
