import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from aiogram.types import FSInputFile
from sqlalchemy import select

from app.bot.factory import create_bot
from app.core.config import get_settings
from app.db.models import DownloadJob, JobStatus, MediaCache
from app.db.session import SyncSessionLocal
from app.services.cache import cache_key, local_cache_path, normalize_url, platform_from_url
from app.services.media import MediaProcessingError, cleanup_partial_files, ensure_compatible_mp4, probe_media
from app.services.storage import ensure_free_space, expires_at, make_token, safe_unlink
from app.services.ytdlp import VideoInfoError, download, is_fast_quality

logger = logging.getLogger(__name__)
SUCCESS_CAPTION = "✅ Скачано при помощи: @savefromyttt_bot"


def process_download(job_id: str, metadata_time: float = 0) -> None:
    settings = get_settings()
    timings = new_timings(metadata_time)
    total_started = perf_counter()

    with SyncSessionLocal() as session:
        job = session.get(DownloadJob, job_id)
        if not job:
            return
        normalized_url = normalize_url(job.url)
        platform = platform_from_url(normalized_url)
        key = cache_key(normalized_url, job.quality)
        local_path = local_cache_path(settings.downloads_dir, key)

        try:
            ensure_free_space(settings.downloads_dir)
            job.status = JobStatus.downloading
            session.commit()

            cache_started = perf_counter()
            cached_media = session.scalar(
                select(MediaCache)
                .where(MediaCache.normalized_url == normalized_url, MediaCache.quality == job.quality)
                .order_by(MediaCache.created_at.desc())
            )
            timings["cache_lookup_time"] = perf_counter() - cache_started
            if cached_media and cached_media.telegram_file_id:
                timings["telegram_upload_time"] = send_cached_video(
                    job.chat_id, cached_media.telegram_file_id
                )
                job.status = JobStatus.ready
                session.commit()
                log_timings(job.id, timings, total_started, cache_hit="telegram_file_id")
                return

            if job.quality != "mp3" and local_path.exists():
                file_path = local_path
                probe = probe_media(file_path)
                job.file_path = str(file_path)
                job.file_size = file_path.stat().st_size
                job.expires_at = expires_at()
                if job.file_size > settings.telegram_file_limit_bytes:
                    job.download_token = make_token()
                job.status = JobStatus.ready
                session.commit()
                timings["telegram_upload_time"] = notify_user(
                    str(job.id), normalized_url, platform, key, probe
                )
                log_timings(job.id, timings, total_started, cache_hit="local_file")
                return

            download_started = perf_counter()
            file_path = download(job.url, job.quality, settings.downloads_dir, str(job.id))
            timings["download_time"] = perf_counter() - download_started
            job.status = JobStatus.processing
            session.commit()

            probe = probe_media(file_path)
            if job.quality != "mp3":
                if is_fast_quality(job.quality):
                    logger.info(
                        "fast media job %s codecs: video=%s audio=%s needs_conversion=%s path=%s",
                        job.id,
                        probe.video_codec,
                        probe.audio_codec,
                        probe.needs_conversion,
                        file_path,
                    )
                    if probe.needs_conversion:
                        raise MediaProcessingError(
                            "fast_incompatible_codec",
                            "Быстрый режим получил несовместимые кодеки. Попробуйте 1080p или Best.",
                        )
                    if file_path.name != f"{job.id}.mp4":
                        final_path = file_path.with_name(f"{job.id}.mp4")
                        file_path.replace(final_path)
                        file_path = final_path
                        probe = probe_media(file_path)
                else:
                    conversion_started = perf_counter()
                    file_path = ensure_compatible_mp4(file_path, str(job.id))
                    timings["conversion_time"] = perf_counter() - conversion_started
                    probe = probe_media(file_path)

            size = file_path.stat().st_size
            logger.info("download job %s final file size=%s path=%s", job.id, size, file_path)

            if job.quality != "mp3":
                local_path.parent.mkdir(parents=True, exist_ok=True)
                if file_path.resolve() != local_path.resolve():
                    shutil.copy2(file_path, local_path)

            job.file_path = str(file_path)
            job.file_size = size
            job.expires_at = expires_at()
            if size > settings.telegram_file_limit_bytes:
                job.download_token = make_token()
            job.status = JobStatus.ready
            session.commit()
            timings["telegram_upload_time"] = notify_user(str(job.id), normalized_url, platform, key, probe)
            log_timings(job.id, timings, total_started)
            return
        except VideoInfoError as exc:
            fail_job(session, job, settings.downloads_dir, exc.code, str(exc))
        except MediaProcessingError as exc:
            fail_job(session, job, settings.downloads_dir, exc.code, str(exc))
        except RuntimeError as exc:
            message = "Недостаточно места на диске" if str(exc) == "insufficient_disk_space" else str(exc)
            fail_job(session, job, settings.downloads_dir, str(exc), message)
        except Exception as exc:
            fail_job(session, job, settings.downloads_dir, "unexpected_error", str(exc))

    log_timings(job_id, timings, total_started)
    notify_user(str(job_id), None, None, None, None)


def new_timings(metadata_time: float) -> dict[str, float]:
    return {
        "metadata_time": metadata_time,
        "cache_lookup_time": 0,
        "download_time": 0,
        "merge_time": 0,
        "conversion_time": 0,
        "telegram_upload_time": 0,
    }


def log_timings(job_id, timings: dict[str, float], total_started: float, cache_hit: str | None = None) -> None:
    logger.info(
        "job %s timings metadata_time=%.3f cache_lookup_time=%.3f download_time=%.3f "
        "merge_time=%.3f conversion_time=%.3f telegram_upload_time=%.3f total_time=%.3f cache_hit=%s",
        job_id,
        timings["metadata_time"],
        timings["cache_lookup_time"],
        timings["download_time"],
        timings["merge_time"],
        timings["conversion_time"],
        timings["telegram_upload_time"],
        perf_counter() - total_started,
        cache_hit,
    )


def fail_job(session, job, downloads_dir: Path, code: str, message: str) -> None:
    cleanup_failed_download(downloads_dir, str(job.id), job.file_path)
    job.status = JobStatus.failed
    job.error_code = code
    job.error_message = message
    session.commit()


def cleanup_failed_download(downloads_dir: Path, job_id: str, file_path: str | None) -> None:
    cleanup_partial_files(downloads_dir, job_id)
    safe_unlink(file_path)
    for path in downloads_dir.glob(f"{job_id}*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def send_cached_video(chat_id: int, telegram_file_id: str) -> float:
    import asyncio

    async def _send() -> None:
        async with create_bot() as bot:
            await bot.send_video(chat_id, telegram_file_id, caption=SUCCESS_CAPTION, supports_streaming=True)

    started = perf_counter()
    asyncio.run(_send())
    return perf_counter() - started


def notify_user(
    job_id: str,
    normalized_url: str | None,
    platform: str | None,
    key: str | None,
    probe,
) -> float:
    import asyncio

    async def _send() -> None:
        settings = get_settings()
        async with create_bot() as bot:
            with SyncSessionLocal() as session:
                job = session.get(DownloadJob, job_id)
                if not job:
                    return
                if job.status == JobStatus.failed:
                    await bot.send_message(job.chat_id, f"Задача завершилась ошибкой: {job.error_message}")
                    return
                if not job.file_path or job.file_size is None:
                    await bot.send_message(job.chat_id, "Файл не найден после скачивания")
                    return
                if job.file_size > settings.telegram_file_limit_bytes:
                    link = f"{settings.public_base_url.rstrip('/')}/downloads/{job.download_token}"
                    await bot.send_message(
                        job.chat_id,
                        f"Файл больше {settings.max_telegram_file_mb} MB. Ссылка активна 3 часа:\n{link}",
                    )
                    return

                path = Path(job.file_path)
                if path.suffix.lower() == ".mp4":
                    try:
                        message = await bot.send_video(
                            job.chat_id,
                            FSInputFile(job.file_path),
                            caption=SUCCESS_CAPTION,
                            supports_streaming=True,
                            duration=probe.duration if probe else None,
                            width=probe.width if probe else None,
                            height=probe.height if probe else None,
                        )
                    except Exception:
                        logger.exception("send_video failed for job %s; falling back to send_document", job.id)
                        await bot.send_document(job.chat_id, FSInputFile(job.file_path), caption=SUCCESS_CAPTION)
                        return
                    if message.video and normalized_url and key:
                        upsert_media_cache(session, job, normalized_url, platform, message.video, probe)
                    return

                await bot.send_document(job.chat_id, FSInputFile(job.file_path), caption=SUCCESS_CAPTION)

    started = perf_counter()
    asyncio.run(_send())
    return perf_counter() - started


def upsert_media_cache(session, job, normalized_url: str, platform: str | None, video, probe) -> None:
    cached = session.scalar(
        select(MediaCache).where(MediaCache.normalized_url == normalized_url, MediaCache.quality == job.quality)
    )
    if cached is None:
        cached = MediaCache(source_url=job.url, normalized_url=normalized_url, platform=platform, quality=job.quality)
        session.add(cached)
    cached.telegram_file_id = video.file_id
    cached.file_unique_id = video.file_unique_id
    cached.title = job.title
    cached.duration = probe.duration if probe else None
    cached.width = probe.width if probe else None
    cached.height = probe.height if probe else None
    session.commit()


def cleanup_expired() -> int:
    now = datetime.now(UTC)
    deleted = 0
    with SyncSessionLocal() as session:
        jobs = session.scalars(
            select(DownloadJob).where(DownloadJob.expires_at.is_not(None), DownloadJob.expires_at < now)
        ).all()
        for job in jobs:
            safe_unlink(job.file_path)
            job.status = JobStatus.expired
            job.download_token = None
            deleted += 1
        session.commit()
    return deleted
