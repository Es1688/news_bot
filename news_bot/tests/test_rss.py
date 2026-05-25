from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_bot.config.loader import SourceConfig
from news_bot.parsers.rss import RssFetcher


@pytest.fixture
def rss_source() -> SourceConfig:
    return SourceConfig(
        name="Broken Feed",
        type="rss",
        url="https://example.com/feed.xml",
        enabled=True,
        category="test",
    )


@pytest.mark.asyncio
async def test_unreachable_rss_returns_empty_list(rss_source: SourceConfig) -> None:
    fetcher = RssFetcher()

    mock_response = AsyncMock()
    mock_response.__aenter__.side_effect = TimeoutError("connection timed out")
    mock_response.__aexit__.return_value = None

    mock_session = AsyncMock()
    mock_session.get.return_value = mock_response
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    with patch("news_bot.parsers.rss.aiohttp.ClientSession", return_value=mock_session):
        items = await fetcher.fetch(rss_source, max_news=5, timeout=5)

    assert items == []


@pytest.mark.asyncio
async def test_broken_xml_returns_empty_or_partial(rss_source: SourceConfig) -> None:
    fetcher = RssFetcher()
    broken_xml = b"<rss><channel><item><title>Bad"

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.read = AsyncMock(return_value=broken_xml)

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_get.__aexit__.return_value = None

    mock_session = AsyncMock()
    mock_session.get.return_value = mock_get
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    with patch("news_bot.parsers.rss.aiohttp.ClientSession", return_value=mock_session):
        items = await fetcher.fetch(rss_source, max_news=5, timeout=5)

    assert isinstance(items, list)


@pytest.mark.asyncio
async def test_non_rss_source_type_returns_empty() -> None:
    fetcher = RssFetcher()
    source = SourceConfig(
        name="HTML source",
        type="html",
        url="https://example.com",
        enabled=True,
    )

    items = await fetcher.fetch(source, max_news=5, timeout=5)

    assert items == []


@pytest.mark.asyncio
async def test_disabled_source_returns_empty() -> None:
    fetcher = RssFetcher()
    source = SourceConfig(
        name="Disabled",
        type="rss",
        url="https://example.com/feed.xml",
        enabled=False,
    )

    items = await fetcher.fetch(source, max_news=5, timeout=5)

    assert items == []
