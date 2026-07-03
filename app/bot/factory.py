from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from app.core.config import get_settings


def create_bot() -> Bot:
    settings = get_settings()
    session = None
    if settings.bot_api_base_url:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.bot_api_base_url.rstrip("/"), is_local=True)
        )
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
