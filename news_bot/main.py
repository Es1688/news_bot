from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timezone

import aiohttp
import aiohttp_socks
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from news_bot.bot.error_handler import register_error_handler
from news_bot.bot.handlers import create_router
from news_bot.bot.scheduler import factory_scheduler_loop, scheduler_loop
from news_bot.config.loader import load_config
from news_bot.core.factory import ContentFactory
from news_bot.core.pipeline import Pipeline
from news_bot.parsers.composite import CompositeFetcher
from news_bot.publishers.alerter import TelegramAlerter
from news_bot.publishers.post import PostPublisher
from news_bot.publishers.telegram import TelegramPublisher
from news_bot.utils.db import Database
from news_bot.utils.logging import setup_logging
from news_bot.writers.llm import LlmWriter


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

    # One shared ClientSession per process: RSS fetching (both cycles) and
    # the LLM writer; closed in the finally block below.
    http_session: aiohttp.ClientSession | None = None
    # Optional separate session for the LLM writer: local setups may need
    # LLM traffic proxied (LLM_PROXY) while RSS stays direct; empty on VPS.
    llm_session: aiohttp.ClientSession | None = None
    if config.factory.enabled:
        http_session = aiohttp.ClientSession()
        if config.factory.llm.proxy:
            llm_session = aiohttp.ClientSession(
                connector=aiohttp_socks.ProxyConnector.from_url(
                    config.factory.llm.proxy
                )
            )

    publisher = TelegramPublisher(bot, config.channel_id)
    fetcher = CompositeFetcher(session=http_session)
    pipeline = Pipeline(config, fetcher, publisher, db)

    publish_lock = asyncio.Lock()
    started_at = datetime.now(timezone.utc)

    factory: ContentFactory | None = None
    factory_lock: asyncio.Lock | None = None
    if config.factory.enabled:
        llm = config.factory.llm
        writer = LlmWriter(
            base_url=llm.base_url,
            api_key=llm.api_key,
            model=llm.model,
            timeout=llm.timeout,
            max_tokens=llm.max_tokens,
            temperature=llm.temperature,
            prompt=config.factory.prompt,
            session=llm_session or http_session,
            disable_reasoning=llm.disable_reasoning,
        )
        post_publisher = PostPublisher(bot, config.channel_id, config.admin_ids)
        alerter = TelegramAlerter(bot, config.admin_ids)
        factory = ContentFactory(config, fetcher, writer, post_publisher, alerter, db)
        factory_lock = asyncio.Lock()

    router = create_router(
        config,
        pipeline,
        db,
        publish_lock,
        started_at,
        factory=factory,
        factory_lock=factory_lock,
        bot=bot,
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    register_error_handler(dispatcher, db)

    scheduler_task = asyncio.create_task(
        scheduler_loop(pipeline, config.settings.post_interval_hours, publish_lock, db)
    )
    factory_task = None
    if factory is not None and factory_lock is not None:
        factory_task = asyncio.create_task(
            factory_scheduler_loop(
                factory, config.factory.interval_hours, factory_lock, db
            )
        )

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        if factory_task is not None:
            factory_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await factory_task
        if http_session is not None:
            await http_session.close()
        if llm_session is not None:
            await llm_session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
