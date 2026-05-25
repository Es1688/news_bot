from __future__ import annotations

from dataclasses import dataclass

from news_bot.core.models import NewsItem


@dataclass(frozen=True)
class KeywordFilter:
    include_keywords: list[str]
    exclude_keywords: list[str]

    def passes(self, item: NewsItem) -> bool:
        title = item.title.lower()
        if self._matches_any(title, self.exclude_keywords):
            return False
        if not self.include_keywords:
            return True
        return self._matches_any(title, self.include_keywords)

    @staticmethod
    def _matches_any(text: str, keywords: list[str]) -> bool:
        for keyword in keywords:
            cleaned = keyword.strip().lower()
            if cleaned and cleaned in text:
                return True
        return False
