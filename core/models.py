from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: datetime | None = None
    category: str | None = None


@dataclass(frozen=True)
class PublishedResult:
    success: bool
    published: int
    failed: int = 0
