from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from news_bot.config.loader import AppConfig
from news_bot.core.pipeline import Pipeline
from news_bot.utils.db import Database
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)


def create_router(
    config: AppConfig,
    pipeline: Pipeline,
    db: Database,
    publish_lock: asyncio.Lock,
    started_at: datetime,
) -> Router:
    router = Router()

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        uptime = datetime.now(timezone.utc) - started_at
        last_run = await db.get_last_event("run")
        last_error = await db.get_last_event("error")
        await message.answer(
            "\n".join(
                [
                    f"Uptime: {format_timedelta(uptime)}",
                    f"Last run: {format_event(last_run)}",
                    f"Last error: {format_event(last_error)}",
                ]
            )
        )

    @router.message(Command("sources"))
    async def sources_handler(message: Message) -> None:
        lines = []
        for source in config.sources:
            status = "enabled" if source.enabled else "disabled"
            category = f" ({source.category})" if source.category else ""
            lines.append(f"- {source.name}{category}: {status}")
        await message.answer("\n".join(lines) if lines else "No sources configured.")

    @router.message(Command("stats"))
    async def stats_handler(message: Message) -> None:
        stats = await db.get_daily_stats()
        if not stats:
            await message.answer("No stats yet.")
            return
        lines = ["Daily stats:"]
        for item in stats:
            lines.append(
                f"{item['day']}: publish={item['publishes']} errors={item['errors']}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("news"))
    async def news_handler(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id not in config.admin_ids:
            await message.answer("Access denied.")
            return
        async with publish_lock:
            await message.answer("Running pipeline...")
            result = await pipeline.run()
        await message.answer(
            f"Pipeline done: collected={result.collected} published={result.published}"
        )

    return router


def format_event(event: dict | None) -> str:
    if not event:
        return "n/a"
    return f"{event['created_at']} ({event.get('details') or 'no details'})"


def format_timedelta(delta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


##### проверка деплоя