from __future__ import annotations

from news_bot.config.loader import SourceConfig
from news_bot.core.models import NewsItem, PublishedResult


class MockFetcher:
    def __init__(
        self,
        items: list[NewsItem] | None = None,
        items_by_source: dict[str, list[NewsItem]] | None = None,
    ) -> None:
        self.items = items or []
        self.items_by_source = items_by_source or {}
        self.fetch_calls: list[tuple] = []

    async def fetch(self, source: SourceConfig, max_news: int, timeout: int) -> list[NewsItem]:
        self.fetch_calls.append((source, max_news, timeout))
        if source.name in self.items_by_source:
            return self.items_by_source[source.name][:max_news]
        return self.items[:max_news]


class MockPublisher:
    def __init__(self, *, success: bool = True, raise_on_publish: Exception | None = None) -> None:
        self.success = success
        self.raise_on_publish = raise_on_publish
        self.publish_calls: list[list[NewsItem]] = []

    async def publish(self, items: list[NewsItem]) -> PublishedResult:
        self.publish_calls.append(list(items))
        if self.raise_on_publish:
            raise self.raise_on_publish
        if not items:
            return PublishedResult(success=True, published=0)
        if self.success:
            return PublishedResult(success=True, published=len(items))
        return PublishedResult(success=False, published=0, failed=len(items))
