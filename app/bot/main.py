import asyncio
import logging

from aiogram import Dispatcher

from app.bot.factory import create_bot
from app.bot.handlers import register_handlers
from app.db.init_db import init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = create_bot()
    dp = Dispatcher()
    register_handlers(dp)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
