from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.services.media import cleanup_partial_files


class VideoInfoError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class FormatOption:
    key: str
    label: str


DEFAULT_OPTIONS = [
    FormatOption("360", "360p"),
    FormatOption("480", "480p"),
    FormatOption("720", "720p"),
    FormatOption("1080", "1080p"),
    FormatOption("best", "Best"),
    FormatOption("mp3", "MP3"),
]


def extract_info(url: str) -> dict[str, Any]:
    opts = {"quiet": True, "skip_download": True, "noplaylist": True, "socket_timeout": 20}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        msg = str(exc).lower()
        if "private" in msg:
            raise VideoInfoError("private_video", "Видео приватное или требует авторизацию") from exc
        if "unsupported url" in msg:
            raise VideoInfoError("unsupported_url", "Ссылка не поддерживается") from exc
        raise VideoInfoError("video_unavailable", "Видео недоступно или ссылка некорректна") from exc
    except Exception as exc:
        raise VideoInfoError("yt_dlp_error", "Не удалось получить информацию о видео") from exc
    if not info:
        raise VideoInfoError("video_unavailable", "Видео недоступно")
    return info


def public_info(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": info.get("title") or "Без названия",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "formats": [option.__dict__ for option in DEFAULT_OPTIONS],
    }


def format_selector(quality: str) -> str:
    if quality == "best":
        return "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1]/best"
    if quality == "mp3":
        return "bestaudio/best"
    if quality in {"360", "480", "720"}:
        return (
            f"best[ext=mp4][height<={quality}][vcodec^=avc1]/"
            f"best[ext=mp4][height<={quality}][vcodec!*=av01][vcodec!*=vp9][vcodec!*=vp09]/"
            f"bestvideo[vcodec^=avc1][height<={quality}]+bestaudio[acodec^=mp4a]/"
            f"best[vcodec^=avc1][height<={quality}]/best[height<={quality}]"
        )
    return (
        f"bestvideo[vcodec^=avc1][height<={quality}]+bestaudio[acodec^=mp4a]/"
        f"best[vcodec^=avc1][height<={quality}]/best[height<={quality}]"
    )


def is_fast_quality(quality: str) -> bool:
    return quality in {"360", "480", "720"}


def download(url: str, quality: str, output_dir: Path, job_id: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(output_dir / f"{job_id}.%(ext)s")
    opts: dict[str, Any] = {
        "format": format_selector(quality),
        "outtmpl": outtmpl,
        "noplaylist": True,
        "nopart": True,
        "quiet": True,
        "retries": 10,
        "fragment_retries": 10,
        "merge_output_format": "mp4",
        "remuxvideo": "mp4",
        "postprocessor_args": ["-movflags", "+faststart"],
    }
    if quality == "mp3":
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except DownloadError as exc:
        cleanup_partial_files(output_dir, job_id)
        msg = str(exc).lower()
        if "ffmpeg" in msg:
            raise VideoInfoError("ffmpeg_error", "Ошибка ffmpeg при обработке файла") from exc
        raise VideoInfoError("yt_dlp_error", "Ошибка yt-dlp при скачивании") from exc
    matches = [path for path in output_dir.glob(f"{job_id}.*") if not path.name.endswith((".part", ".ytdl"))]
    if not matches:
        raise VideoInfoError("yt_dlp_error", "Файл не был создан")
    return max(matches, key=lambda p: p.stat().st_size)
