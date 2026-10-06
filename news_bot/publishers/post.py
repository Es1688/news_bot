from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from news_bot.core.models import Post
from news_bot.utils.logging import get_logger
from news_bot.utils.sanitize import sanitize_html


logger = get_logger(__name__)

_MAX_ERROR_LEN = 300
_MAX_SEND_ATTEMPTS = 3  # total tries per message on flood control
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


@dataclass(frozen=True)
class PostPublishResult:
    success: bool
    message_id: int | None
    error: str | None
    # "content" (text itself is unusable — burns an attempt) or "infra"
    # (network/flood — retried for free, plan P0.3); None means unknown/infra
    error_kind: str | None = None


class PostPublisherProtocol(Protocol):
    async def publish_post(
        self, post: Post, *, to_admins: bool = False
    ) -> PostPublishResult: ...


class PostPublisher:
    """Publishes finished posts to the channel (or admins in dry-run mode).

    The source link is appended by this code — the LLM never emits links.
    """

    # pause between consecutive Telegram sends (channel posts and admin
    # copies share the same rate limits); tests shrink it to zero
    SEND_PAUSE_SECONDS: float = 2.5

    def __init__(self, bot: Bot, channel_id: str, admin_ids: list[int]) -> None:
        self._bot = bot
        self._channel_id = channel_id
        self._admin_ids = list(admin_ids)
        self._sends = 0

    async def publish_post(
        self, post: Post, *, to_admins: bool = False
    ) -> PostPublishResult:
        if not post.text or not post.text.strip():
            return PostPublishResult(
                success=False,
                message_id=None,
                error="post text is empty",
                error_kind="content",
            )

        if to_admins:
            return await self._publish_to_admins(post)
        return await self._publish_to_channel(post)

    async def _publish_to_channel(self, post: Post) -> PostPublishResult:
        text = sanitize_html(post.text)
        try:
            message_id = await self._send_with_retries(
                self._channel_id, _channel_message(text, post, html_url=True)
            )
        except TelegramBadRequest as exc:
            if not _is_parse_error(exc):
                return self._error(exc)
            logger.warning("post parse_mode failed, retrying plain: %s", exc)
            try:
                message_id = await self._send_with_retries(
                    self._channel_id,
                    _channel_message(_plain_text(post.text), post, html_url=False),
                    parse_mode=None,
                )
            except Exception as plain_exc:
                return self._error(plain_exc)
        except Exception as exc:
            return self._error(exc)
        return PostPublishResult(
            success=True, message_id=message_id, error=None, error_kind=None
        )

    async def _publish_to_admins(self, post: Post) -> PostPublishResult:
        text = sanitize_html(post.text)
        message = "[DRY-RUN] " + _channel_message(text, post, html_url=True)
        delivered = 0
        for admin_id in self._admin_ids:
            try:
                await self._send_with_retries(admin_id, message)
                delivered += 1
            except Exception as exc:
                # one admin failing must not block the other previews
                logger.error("admin_preview_failed admin_id=%s error=%s", admin_id, exc)
        if not delivered:
            return PostPublishResult(
                success=False,
                message_id=None,
                error=f"no admin preview delivered ({len(self._admin_ids)} admins)",
                error_kind="infra",
            )
        return PostPublishResult(
            success=True, message_id=None, error=None, error_kind=None
        )

    async def _send_with_retries(
        self, chat_id: str | int, message: str, *, parse_mode: str | None = "HTML"
    ) -> int:
        """send_message with flood-control retry; returns message_id."""
        for attempt in range(1, _MAX_SEND_ATTEMPTS + 1):
            if self._sends > 0:
                await asyncio.sleep(self.SEND_PAUSE_SECONDS)
            try:
                if parse_mode:
                    sent = await self._bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode=parse_mode,
                        disable_web_page_preview=False,
                    )
                else:
                    sent = await self._bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        disable_web_page_preview=False,
                    )
                self._sends += 1
                return int(sent.message_id)
            except TelegramRetryAfter as exc:
                if attempt == _MAX_SEND_ATTEMPTS:
                    raise
                logger.warning(
                    "flood control, sleeping %ss (attempt %s/%s)",
                    exc.retry_after,
                    attempt,
                    _MAX_SEND_ATTEMPTS,
                )
                await asyncio.sleep(max(exc.retry_after, 0))
        raise AssertionError("unreachable")

    def _error(self, exc: Exception) -> PostPublishResult:
        message = f"{type(exc).__name__}: {exc}"
        kind = _classify_send_error(exc)
        logger.error("post_publish_failed kind=%s error=%s", kind, message)
        return PostPublishResult(
            success=False,
            message_id=None,
            error=message[:_MAX_ERROR_LEN],
            error_kind=kind,
        )


def _channel_message(text: str, post: Post, *, html_url: bool) -> str:
    # the source link is added by the code, never by the LLM; "&" in the URL
    # must be escaped when the message is sent as HTML
    url = html.escape(post.news_url, quote=True) if html_url else post.news_url
    return f"{text}\nИсточник: {url}"


def _plain_text(text: str) -> str:
    # full fallback: tags stripped, everything escaped
    return html.escape(html.unescape(_TAG_RE.sub("", text)), quote=False)


def _is_parse_error(exc: TelegramBadRequest) -> bool:
    return "can't parse entities" in str(exc).lower()


def _is_too_long(exc: TelegramBadRequest) -> bool:
    return "message is too long" in str(exc).lower()


def _classify_send_error(exc: Exception) -> str:
    """Infra send failures (network, flood control) must not burn attempts;
    content ones mean the text itself is unusable (plan P0.3)."""
    if isinstance(exc, (TelegramRetryAfter, TelegramNetworkError)):
        return "infra"
    if isinstance(exc, TelegramBadRequest):
        return (
            "content"
            if (_is_parse_error(exc) or _is_too_long(exc))
            else "infra"
        )
    return "infra"
