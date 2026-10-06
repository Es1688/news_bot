from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from news_bot.core.models import Post
from news_bot.publishers.post import PostPublisher

_CHANNEL = "-1001234567890"
_ADMINS = [111, 222, 333]
_NEWS_URL = "https://example.com/news"

_POST_TEXT = (
    "<b>Релиз Python 3.13</b> принесёт экспериментальный JIT-компилятор и "
    "новый интерактивный REPL. Разработчики отмечают ускорение старта "
    "интерпретатора и улучшенные сообщения об ошибках. Совместимость с "
    "популярными фреймворками сохраняется."
)


def make_post(text: str | None = _POST_TEXT) -> Post:
    return Post(
        id=7,
        news_url=_NEWS_URL,
        source="Example",
        title="Python 3.13",
        text=text,
        status="draft",
    )


@pytest.fixture(autouse=True)
def no_send_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PostPublisher, "SEND_PAUSE_SECONDS", 0.0)


def make_bot(side_effect=None, message_id: int = 42) -> AsyncMock:
    bot = AsyncMock()
    if side_effect is not None:
        bot.send_message.side_effect = side_effect
    else:
        bot.send_message.return_value = SimpleNamespace(message_id=message_id)
    return bot


def make_publisher(bot: AsyncMock) -> PostPublisher:
    return PostPublisher(bot=bot, channel_id=_CHANNEL, admin_ids=list(_ADMINS))


def call_kwargs(bot: AsyncMock, index: int = 0) -> dict:
    return bot.send_message.await_args_list[index].kwargs


async def test_channel_send_appends_source_link_and_uses_html() -> None:
    bot = make_bot(message_id=42)
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is True
    assert result.message_id == 42
    assert result.error is None
    bot.send_message.assert_awaited_once()
    kwargs = call_kwargs(bot)
    assert kwargs["chat_id"] == _CHANNEL
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["disable_web_page_preview"] is False
    # sanitized post text + the code-added source link
    assert kwargs["text"].startswith("<b>Релиз Python 3.13</b>")
    assert kwargs["text"].endswith(f"\nИсточник: {_NEWS_URL}")


async def test_text_is_sanitized_before_sending() -> None:
    bot = make_bot()
    publisher = make_publisher(bot)
    post = make_post("<b>ok</b> & <script>bad()</script> 5 < 6")

    await publisher.publish_post(post)

    text = call_kwargs(bot)["text"]
    assert "<b>ok</b>" in text
    assert "<script>" not in text
    assert "&amp;" in text and "&lt;" in text


async def test_retry_after_is_retried_and_succeeds() -> None:
    flood = TelegramRetryAfter(method=None, message="flood", retry_after=0)
    bot = make_bot(side_effect=[flood, SimpleNamespace(message_id=7)])
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is True
    assert result.message_id == 7
    assert bot.send_message.await_count == 2


async def test_retry_after_exhausts_after_three_attempts() -> None:
    flood = TelegramRetryAfter(method=None, message="flood", retry_after=0)
    bot = make_bot(side_effect=[flood, flood, flood])
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is False
    assert result.message_id is None
    assert result.error is not None
    assert result.error_kind == "infra"  # flood control must not burn attempts
    assert bot.send_message.await_count == 3


async def test_parse_mode_error_falls_back_to_plain_text() -> None:
    parse_error = TelegramBadRequest(
        method=None, message="Bad Request: can't parse entities: unsupported tag"
    )
    bot = make_bot(side_effect=[parse_error, SimpleNamespace(message_id=9)])
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is True
    assert result.message_id == 9
    assert bot.send_message.await_count == 2
    plain_kwargs = call_kwargs(bot, index=1)
    assert "parse_mode" not in plain_kwargs
    # fallback text: tags stripped, everything escaped, link still appended
    assert "<b>" not in plain_kwargs["text"]
    assert "&lt;b&gt;" not in plain_kwargs["text"]
    assert plain_kwargs["text"].endswith(f"\nИсточник: {_NEWS_URL}")
    assert "Релиз Python 3.13" in plain_kwargs["text"]


async def test_other_bad_request_errors_are_reported_without_fallback() -> None:
    error = TelegramBadRequest(method=None, message="Bad Request: chat not found")
    bot = make_bot(side_effect=error)
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is False
    assert result.message_id is None
    assert result.error is not None
    assert "chat not found" in result.error
    # chat problems are infra for the post: the text itself is fine
    assert result.error_kind == "infra"
    assert bot.send_message.await_count == 1


async def test_too_long_message_is_content_error() -> None:
    error = TelegramBadRequest(
        method=None, message="Bad Request: message is too long"
    )
    bot = make_bot(side_effect=error)
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is False
    assert result.error_kind == "content"
    bot.send_message.assert_awaited_once()


async def test_admins_mode_sends_preview_to_every_admin() -> None:
    bot = make_bot(message_id=55)
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post(), to_admins=True)

    assert result.success is True
    # dry-run previews carry no channel message id
    assert result.message_id is None
    assert bot.send_message.await_count == len(_ADMINS)
    sent_to = [call_kwargs(bot, i)["chat_id"] for i in range(len(_ADMINS))]
    assert sent_to == _ADMINS
    for i in range(len(_ADMINS)):
        kwargs = call_kwargs(bot, i)
        assert kwargs["text"].startswith("[DRY-RUN] ")
        assert kwargs["text"].endswith(f"\nИсточник: {_NEWS_URL}")


async def test_one_admin_failure_does_not_block_others() -> None:
    bot = make_bot(
        side_effect=[
            RuntimeError("dm closed"),
            SimpleNamespace(message_id=1),
            SimpleNamespace(message_id=2),
        ]
    )
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post(), to_admins=True)

    assert result.success is True
    assert result.message_id is None
    assert bot.send_message.await_count == 3


async def test_admins_mode_all_failures_report_error() -> None:
    bot = make_bot(side_effect=RuntimeError("no dm"))
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post(), to_admins=True)

    assert result.success is False
    assert result.message_id is None
    assert result.error is not None


async def test_generic_exception_is_reported_not_raised() -> None:
    bot = make_bot(side_effect=RuntimeError("network down"))
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.success is False
    assert result.message_id is None
    assert "network down" in (result.error or "")
    assert result.error_kind == "infra"


async def test_empty_post_text_is_rejected() -> None:
    bot = make_bot()
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post(text="   "))

    assert result.success is False
    assert "empty" in (result.error or "")
    assert result.error_kind == "content"
    bot.send_message.assert_not_awaited()


async def test_source_link_ampersand_is_escaped_in_html() -> None:
    from dataclasses import replace

    bot = make_bot(message_id=5)
    publisher = make_publisher(bot)
    post = replace(make_post(), news_url="https://example.com/news?a=1&b=2")

    result = await publisher.publish_post(post)

    assert result.success is True
    text = call_kwargs(bot)["text"]
    assert text.endswith("\nИсточник: https://example.com/news?a=1&amp;b=2")


async def test_error_text_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = make_bot(side_effect=RuntimeError("x" * 1000))
    publisher = make_publisher(bot)

    result = await publisher.publish_post(make_post())

    assert result.error is not None
    assert len(result.error) <= 300


async def test_pause_applies_between_consecutive_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PostPublisher, "SEND_PAUSE_SECONDS", 0.1)
    bot = make_bot(message_id=1)
    publisher = make_publisher(bot)

    started = time.monotonic()
    await publisher.publish_post(make_post())
    first_send_elapsed = time.monotonic() - started

    started = time.monotonic()
    await publisher.publish_post(make_post())
    second_send_elapsed = time.monotonic() - started

    # first send is immediate, the following one waits out the pause
    assert first_send_elapsed < 0.09
    assert second_send_elapsed >= 0.09
