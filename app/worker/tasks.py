from datetime import UTC, datetime

from sqlalchemy import select

from app.bot.factory import create_bot
from app.core.config import get_settings
from app.db.models import DownloadJob, JobStatus
from app.db.session import SyncSessionLocal
from app.services.storage import ensure_free_space, expires_at, make_token, safe_unlink
from app.services.ytdlp import VideoInfoError, download


def process_download(job_id: str) -> None:
    settings = get_settings()
    with SyncSessionLocal() as session:
        job = session.get(DownloadJob, job_id)
        if not job:
            return
        try:
            ensure_free_space(settings.downloads_dir)
            job.status = JobStatus.downloading
            session.commit()
            file_path = download(job.url, job.quality, settings.downloads_dir, str(job.id))
            job.status = JobStatus.processing
            session.commit()
            size = file_path.stat().st_size
            job.file_path = str(file_path)
            job.file_size = size
            job.expires_at = expires_at()
            if size > settings.telegram_file_limit_bytes:
                job.download_token = make_token()
            job.status = JobStatus.ready
            session.commit()
        except VideoInfoError as exc:
            job.status = JobStatus.failed
            job.error_code = exc.code
            job.error_message = str(exc)
            session.commit()
        except RuntimeError as exc:
            job.status = JobStatus.failed
            job.error_code = str(exc)
            job.error_message = "Недостаточно места на диске" if str(exc) == "insufficient_disk_space" else str(exc)
            session.commit()
        except Exception as exc:
            job.status = JobStatus.failed
            job.error_code = "unexpected_error"
            job.error_message = str(exc)
            session.commit()

    notify_user(job_id)


def notify_user(job_id: str) -> None:
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
                if job.file_size <= settings.telegram_file_limit_bytes:
                    from aiogram.types import FSInputFile

                    await bot.send_document(job.chat_id, FSInputFile(job.file_path), caption="Готово")
                else:
                    link = f"{settings.public_base_url.rstrip('/')}/downloads/{job.download_token}"
                    await bot.send_message(job.chat_id, f"Файл больше 1900 MB. Ссылка активна 3 часа:\n{link}")

    asyncio.run(_send())


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
