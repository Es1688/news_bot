from __future__ import annotations

import pytest

from news_bot.core.models import NewsItem
from news_bot.utils.db import Database


@pytest.mark.asyncio
async def test_new_item_is_not_sent(db: Database, sample_item: NewsItem) -> None:
    assert await db.is_sent(sample_item.url) is False


@pytest.mark.asyncio
async def test_mark_sent_makes_item_sent(db: Database, sample_item: NewsItem) -> None:
    await db.mark_sent(sample_item)
    assert await db.is_sent(sample_item.url) is True


@pytest.mark.asyncio
async def test_mark_sent_idempotent(db: Database, sample_item: NewsItem) -> None:
    await db.mark_sent(sample_item)
    await db.mark_sent(sample_item)
    assert await db.is_sent(sample_item.url) is True


@pytest.mark.asyncio
async def test_log_event_and_get_last_event(db: Database) -> None:
    await db.log_event("run", "collected=3 published=1")

    event = await db.get_last_event("run")

    assert event is not None
    assert event["details"] == "collected=3 published=1"


@pytest.mark.asyncio
async def test_get_last_event_returns_none_when_missing(db: Database) -> None:
    assert await db.get_last_event("nonexistent") is None


@pytest.mark.asyncio
async def test_get_daily_stats(db: Database) -> None:
    await db.log_event("publish", "published=2")
    await db.log_event("error", "publisher_failed")

    stats = await db.get_daily_stats(days=7)

    assert len(stats) >= 1
    assert stats[0]["publishes"] >= 1
    assert stats[0]["errors"] >= 1
