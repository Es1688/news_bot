from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from news_bot.bot.handlers import create_router
from news_bot.bot.scheduler import scheduler_loop
from news_bot.config.loader import load_config
from news_bot.core.pipeline import Pipeline
from news_bot.parsers.composite import CompositeFetcher
from news_bot.publishers.telegram import TelegramPublisher
from news_bot.utils.db import Database
from news_bot.utils.logging import setup_logging


async def main() -> None:
    config = load_config()
    setup_logging(config.log_level)
    db = Database(config.data_path)
    await db.initialize()

    proxy = os.getenv("TELEGRAM_PROXY", "").strip()
    if proxy:
        session = AiohttpSession(proxy=proxy)
        bot = Bot(token=config.bot_token, session=session)
    else:
        bot = Bot(token=config.bot_token)
    publisher = TelegramPublisher(bot, config.channel_id)
    fetcher = CompositeFetcher()
    pipeline = Pipeline(config, fetcher, publisher, db)

    publish_lock = asyncio.Lock()
    started_at = datetime.now(timezone.utc)
    router = create_router(config, pipeline, db, publish_lock, started_at)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    scheduler_task = asyncio.create_task(
        scheduler_loop(pipeline, config.settings.post_interval_hours, publish_lock, db)
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
