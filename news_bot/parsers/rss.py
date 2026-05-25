from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any

import aiohttp
import feedparser

from news_bot.config.loader import SourceConfig
from news_bot.core.models import NewsItem
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)


class RssFetcher:
    async def fetch(
        self, source: SourceConfig, max_news: int, timeout: int
    ) -> list[NewsItem]:
        if source.type != "rss" or not source.enabled:
            return []

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(source.url) as response:
                    response.raise_for_status()
                    payload = await response.read()
        except Exception as exc:
            logger.error(
                "source=%s error=%s",
                source.name,
                exc,
            )
            return []

        parsed = await asyncio.to_thread(feedparser.parse, payload)
        items = []
        for entry in parsed.entries[:max_news]:
            items.append(_entry_to_item(entry, source))
        return items


def _entry_to_item(entry: dict[str, Any], source: SourceConfig) -> NewsItem:
    published_at = _parse_entry_date(entry)
    title = str(entry.get("title", "")).strip()
    link = str(entry.get("link", "")).strip()
    return NewsItem(
        title=title,
        url=link,
        source=source.name,
        published_at=published_at,
        category=source.category,
    )


def _parse_entry_date(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            timestamp = time.mktime(value)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return None
