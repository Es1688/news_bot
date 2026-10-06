from __future__ import annotations

from typing import Protocol

from aiogram import Bot

from news_bot.utils.logging import get_logger


logger = get_logger(__name__)


class Alerter(Protocol):
    async def send_alert(self, text: str) -> None: ...

    async def send_recovery(self, text: str) -> None: ...


class TelegramAlerter:
    """Delivers incident alerts to the admins' DMs.

    Alerting must never break the factory loop: every failure is logged
    and swallowed.
    """

    def __init__(self, bot: Bot, admin_ids: list[int]) -> None:
        self._bot = bot
        self._admin_ids = list(admin_ids)

    async def send_alert(self, text: str) -> None:
        await self._broadcast(text)

    async def send_recovery(self, text: str) -> None:
        await self._broadcast(text)

    async def _broadcast(self, text: str) -> None:
        for admin_id in self._admin_ids:
            try:
                await self._bot.send_message(chat_id=admin_id, text=text)
            except Exception as exc:
                logger.error("alert_delivery_failed admin_id=%s error=%s", admin_id, exc)
