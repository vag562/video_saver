from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_CODECS_TO_CONVERT = {"av1", "vp9"}
AUDIO_CODECS_TO_CONVERT = {"opus"}
COMPATIBLE_VIDEO_CODEC = "h264"
COMPATIBLE_AUDIO_CODEC = "aac"


class MediaProcessingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ProbeResult:
    video_codec: str | None
    audio_codec: str | None
    duration: int | None = None
    width: int | None = None
    height: int | None = None

    @property
    def needs_conversion(self) -> bool:
        if not self.video_codec:
            return False
        return (
            self.video_codec in VIDEO_CODECS_TO_CONVERT
            or self.audio_codec in AUDIO_CODECS_TO_CONVERT
            or self.video_codec != COMPATIBLE_VIDEO_CODEC
            or (self.audio_codec is not None and self.audio_codec != COMPATIBLE_AUDIO_CODEC)
        )


def probe_media(path: Path) -> ProbeResult:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise MediaProcessingError("ffprobe_error", "Не удалось проверить скачанный файл через ffprobe")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError("ffprobe_error", "ffprobe вернул некорректный ответ") from exc

    video_codec = None
    audio_codec = None
    duration = None
    width = None
    height = None
    format_duration = payload.get("format", {}).get("duration")
    if format_duration is not None:
        try:
            duration = int(float(format_duration))
        except (TypeError, ValueError):
            duration = None
    for stream in payload.get("streams", []):
        codec_type = stream.get("codec_type")
        codec_name = stream.get("codec_name")
        if codec_type == "video" and video_codec is None:
            video_codec = codec_name
            width = stream.get("width")
            height = stream.get("height")
            if duration is None and stream.get("duration") is not None:
                try:
                    duration = int(float(stream["duration"]))
                except (TypeError, ValueError):
                    duration = None
        elif codec_type == "audio" and audio_codec is None:
            audio_codec = codec_name
    return ProbeResult(
        video_codec=video_codec,
        audio_codec=audio_codec,
        duration=duration,
        width=width,
        height=height,
    )


def ensure_compatible_mp4(path: Path, job_id: str) -> Path:
    before_size = path.stat().st_size
    initial_probe = probe_media(path)
    final_path = (
        path.with_name(f"{job_id}.mp4")
        if initial_probe.video_codec
        else path.with_name(f"{job_id}{path.suffix}")
    )

    logger.info(
        "media codecs for job %s: video=%s audio=%s needs_conversion=%s size_before=%s path=%s",
        job_id,
        initial_probe.video_codec,
        initial_probe.audio_codec,
        initial_probe.needs_conversion,
        before_size,
        path,
    )

    if initial_probe.video_codec and initial_probe.needs_conversion:
        fixed_path = path.with_name(f"{job_id}_fixed.mp4")
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(fixed_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            fixed_path.unlink(missing_ok=True)
            raise MediaProcessingError("ffmpeg_error", "Не удалось конвертировать видео в совместимый MP4")
        os.replace(fixed_path, final_path)
        if path != final_path:
            path.unlink(missing_ok=True)
    elif path != final_path:
        os.replace(path, final_path)

    final_probe = probe_media(final_path)
    if final_probe.video_codec and final_probe.video_codec != COMPATIBLE_VIDEO_CODEC:
        raise MediaProcessingError("ffmpeg_error", "Итоговый MP4 не прошёл проверку совместимости")
    if final_probe.audio_codec and final_probe.audio_codec != COMPATIBLE_AUDIO_CODEC and final_probe.video_codec:
        raise MediaProcessingError("ffmpeg_error", "Итоговый MP4 не прошёл проверку совместимости")

    after_size = final_path.stat().st_size
    logger.info(
        "media finalized for job %s: video=%s audio=%s size_before=%s size_after=%s final_path=%s",
        job_id,
        final_probe.video_codec,
        final_probe.audio_codec,
        before_size,
        after_size,
        final_path,
    )
    return final_path


def cleanup_partial_files(output_dir: Path, job_id: str) -> None:
    for path in output_dir.glob(f"{job_id}*.part"):
        path.unlink(missing_ok=True)
    for path in output_dir.glob(f"{job_id}*.ytdl"):
        path.unlink(missing_ok=True)
