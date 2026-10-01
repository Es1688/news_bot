from __future__ import annotations

from aiogram import Bot

from news_bot.core.models import NewsItem, PublishedResult
from news_bot.utils.formatter import format_items
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)


class TelegramPublisher:
    def __init__(self, bot: Bot, channel_id: str) -> None:
        self._bot = bot
        self._channel_id = channel_id

    async def publish(self, items: list[NewsItem]) -> PublishedResult:
        if not items:
            return PublishedResult(success=True, published=0)

        messages = format_items(items)
        try:
            for message in messages:
                await self._bot.send_message(
                    chat_id=self._channel_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
        except Exception as exc:
            logger.error("telegram_publish_failed error=%s", exc)
            return PublishedResult(success=False, published=0, failed=len(items))

        return PublishedResult(success=True, published=len(items))
