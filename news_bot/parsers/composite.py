from __future__ import annotations

from urllib.parse import urlparse

from news_bot.config.loader import SourceConfig
from news_bot.core.models import NewsItem
from news_bot.parsers.habr import HabrFetcher
from news_bot.parsers.rss import RssFetcher
from news_bot.parsers.vc_ru import VcRuFetcher
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)


class CompositeFetcher:
    def __init__(self) -> None:
        self._rss = RssFetcher()
        self._habr = HabrFetcher()
        self._vc_ru = VcRuFetcher()

    async def fetch(
        self, source: SourceConfig, max_news: int, timeout: int
    ) -> list[NewsItem]:
        if not source.enabled:
            return []

        if source.type == "rss":
            return await self._rss.fetch(source, max_news, timeout)

        if source.type == "html":
            host = urlparse(source.url).netloc.lower()
            if "habr.com" in host:
                return await self._habr.fetch(source, max_news, timeout)
            if "vc.ru" in host:
                return await self._vc_ru.fetch(source, max_news, timeout)

        logger.warning(
            "source=%s type=%s unsupported",
            source.name,
            source.type,
        )
        return []
