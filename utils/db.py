from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from news_bot.core.models import NewsItem


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sources_state (
                    name TEXT PRIMARY KEY,
                    enabled INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    async def is_sent(self, url: str) -> bool:
        return await asyncio.to_thread(self._is_sent_sync, url)

    def _is_sent_sync(self, url: str) -> bool:
        with sqlite3.connect(self._path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sent_news WHERE url = ? LIMIT 1", (url,)
            )
            return cursor.fetchone() is not None

    async def mark_sent(self, item: NewsItem) -> None:
        await asyncio.to_thread(self._mark_sent_sync, item)

    def _mark_sent_sync(self, item: NewsItem) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_news (url, source, title)
                VALUES (?, ?, ?)
                """,
                (item.url, item.source, item.title),
            )
            conn.commit()

    async def log_event(self, event: str, details: str | None = None) -> None:
        await asyncio.to_thread(self._log_event_sync, event, details)

    def _log_event_sync(self, event: str, details: str | None) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT INTO bot_stats (event, details) VALUES (?, ?)",
                (event, details),
            )
            conn.commit()

    async def get_last_event(self, event: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_last_event_sync, event)

    def _get_last_event_sync(self, event: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT created_at, details
                FROM bot_stats
                WHERE event = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (event,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {"created_at": row["created_at"], "details": row["details"]}

    async def get_daily_stats(self, days: int = 7) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_daily_stats_sync, days)

    def _get_daily_stats_sync(self, days: int) -> list[dict[str, Any]]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    date(created_at) as day,
                    SUM(CASE WHEN event = 'publish' THEN 1 ELSE 0 END) as publishes,
                    SUM(CASE WHEN event = 'error' THEN 1 ELSE 0 END) as errors
                FROM bot_stats
                WHERE created_at >= datetime('now', ?)
                GROUP BY day
                ORDER BY day DESC
                """,
                (f"-{days} days",),
            )
            rows = cursor.fetchall()
            return [
                {"day": row["day"], "publishes": row["publishes"], "errors": row["errors"]}
                for row in rows
            ]
