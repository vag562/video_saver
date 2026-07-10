import json
from time import perf_counter

from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from redis import Redis
from rq import Queue
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import DownloadJob, JobStatus
from app.db.session import AsyncSessionLocal
from app.services.ytdlp import VideoInfoError, extract_info, public_info

URL_PREFIXES = ("http://", "https://")
PENDING_VIDEO_TTL_SECONDS = 1800


def register_handlers(dp: Dispatcher) -> None:
    dp.message.register(start, CommandStart())
    dp.message.register(handle_url, F.text.startswith(URL_PREFIXES))
    dp.callback_query.register(handle_quality, F.data.startswith("quality:"))


def redis_connection() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def pending_video_key(user_id: int, message_id: int) -> str:
    return f"pending-video:{user_id}:{message_id}"


async def start(message: Message) -> None:
    await message.answer("Отправьте ссылку на видео, а я предложу доступные варианты скачивания.")


async def handle_url(message: Message) -> None:
    assert message.text and message.from_user
    await message.answer("Проверяю ссылку через yt-dlp...")
    metadata_started = perf_counter()
    try:
        info = extract_info(message.text.strip())
    except VideoInfoError as exc:
        await message.answer(f"Ошибка: {exc}")
        return
    metadata_time = perf_counter() - metadata_started
    data = public_info(info)
    buttons = [
        [InlineKeyboardButton(text=item["label"], callback_data=f"quality:{item['key']}")]
        for item in data["formats"]
    ]
    sent = await message.answer(
        f"<b>{data['title']}</b>\nДлительность: {data['duration'] or 'неизвестно'} сек.\nВыберите качество:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    redis_connection().setex(
        pending_video_key(message.from_user.id, sent.message_id),
        PENDING_VIDEO_TTL_SECONDS,
        json.dumps(
            {
                "url": message.text.strip(),
                "title": data["title"],
                "metadata_time": metadata_time,
            },
            ensure_ascii=False,
        ),
    )


async def handle_quality(callback: CallbackQuery) -> None:
    assert callback.message and callback.from_user
    parts = (callback.data or "").split(":", 2)
    quality = parts[1] if len(parts) > 1 else "best"
    cached = redis_connection().get(pending_video_key(callback.from_user.id, callback.message.message_id))
    if not cached:
        await callback.answer("Срок выбора качества истёк. Отправьте ссылку заново", show_alert=True)
        return
    payload = json.loads(cached)
    url = payload["url"]
    title = payload.get("title")
    metadata_time = float(payload.get("metadata_time") or 0)

    settings = get_settings()
    async with AsyncSessionLocal() as session:
        if callback.from_user.id not in settings.admin_user_ids:
            active = await session.scalar(
                select(func.count()).select_from(DownloadJob).where(
                    DownloadJob.user_id == callback.from_user.id,
                    DownloadJob.status.in_([JobStatus.pending, JobStatus.downloading, JobStatus.processing]),
                )
            )
            if active:
                await callback.answer("У вас уже есть активная задача", show_alert=True)
                return
        job = DownloadJob(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            url=url,
            title=title,
            quality=quality,
            status=JobStatus.pending,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

    Queue(settings.rq_queue_name, connection=Redis.from_url(settings.redis_url)).enqueue(
        "app.worker.tasks.process_download", str(job.id), metadata_time, job_timeout="6h"
    )
    redis_connection().delete(pending_video_key(callback.from_user.id, callback.message.message_id))
    await callback.message.answer(f"Задача создана: <code>{job.id}</code>\nСтатус: pending")
    await callback.answer()
