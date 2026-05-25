from __future__ import annotations

import asyncio

from news_bot.core.pipeline import Pipeline
from news_bot.utils.db import Database
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)


async def scheduler_loop(
    pipeline: Pipeline,
    interval_hours: int,
    publish_lock: asyncio.Lock,
    db: Database,
) -> None:
    while True:
        async with publish_lock:
            try:
                await pipeline.run()
            except Exception as exc:
                logger.error("scheduler_error error=%s", exc)
                await db.log_event("error", f"scheduler_error={exc}")
        await asyncio.sleep(interval_hours * 3600)
