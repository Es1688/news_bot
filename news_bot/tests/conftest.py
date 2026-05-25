from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_bot.config.loader import (
    AppConfig,
    AppSettings,
    FilterSettings,
    SourceConfig,
)
from news_bot.core.models import NewsItem
from news_bot.utils.db import Database

from news_bot.tests.mocks import MockFetcher, MockPublisher


@pytest.fixture
def sample_item() -> NewsItem:
    return NewsItem(
        title="Python 3.13 released",
        url="https://example.com/python-313",
        source="Python Insider",
        published_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        category="python",
    )


@pytest.fixture
def sample_items() -> list[NewsItem]:
    return [
        NewsItem(
            title="Python news",
            url="https://example.com/1",
            source="Source A",
            category="python",
        ),
        NewsItem(
            title="Rust news",
            url="https://example.com/2",
            source="Source B",
            category="rust",
        ),
    ]


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        bot_token="123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        channel_id="-1001234567890",
        admin_ids=[111, 222],
        log_level="INFO",
        settings=AppSettings(
            post_interval_hours=6,
            max_news_per_source=5,
            request_timeout=30,
        ),
        filters=FilterSettings(
            include_keywords=[],
            exclude_keywords=[],
        ),
        sources=[
            SourceConfig(
                name="Test RSS",
                type="rss",
                url="https://example.com/feed.xml",
                enabled=True,
                category="test",
            ),
            SourceConfig(
                name="Disabled RSS",
                type="rss",
                url="https://example.com/disabled.xml",
                enabled=False,
                category="test",
            ),
        ],
        data_path=tmp_path / "news_bot.db",
    )


@pytest.fixture
async def db(app_config: AppConfig) -> Database:
    database = Database(app_config.data_path)
    await database.initialize()
    return database


@pytest.fixture
def mock_fetcher() -> MockFetcher:
    return MockFetcher()


@pytest.fixture
def mock_publisher() -> MockPublisher:
    return MockPublisher()


@pytest.fixture
def mock_message() -> AsyncMock:
    message = AsyncMock()
    message.answer = AsyncMock()
    return message
