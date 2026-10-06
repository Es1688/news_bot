from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

from aiogram import Dispatcher
from aiogram.types import ErrorEvent, Update

from news_bot.bot.error_handler import (
    _MAX_ERROR_LEN,
    _USER_ERROR_TEXT,
    register_error_handler,
)
from news_bot.utils.db import Database


def _make_event(
    message: MagicMock | None = None,
    callback_query: MagicMock | None = None,
    exception: Exception | None = None,
) -> ErrorEvent:
    # model_construct: real Update instance without field validation,
    # so message/callback_query can stay mocks.
    update = Update.model_construct(
        update_id=1, message=message, callback_query=callback_query
    )
    return ErrorEvent(update=update, exception=exception or ValueError("boom"))


def _registered_callback(db: Database):
    dispatcher = Dispatcher()
    register_error_handler(dispatcher, db)
    assert len(dispatcher.errors.handlers) == 1
    return dispatcher.errors.handlers[0].callback


def _error_records(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR and "unhandled_error" in record.getMessage()
    ]


async def test_registration_wires_single_error_handler() -> None:
    dispatcher = Dispatcher()
    register_error_handler(dispatcher, MagicMock())
    assert len(dispatcher.errors.handlers) == 1


async def test_error_logged_recorded_and_answered(db: Database, caplog) -> None:
    callback = _registered_callback(db)
    message = MagicMock()
    message.answer = AsyncMock()
    event = _make_event(message=message)

    with caplog.at_level(logging.ERROR, logger="news_bot.bot.error_handler"):
        result = await callback(event)

    assert result is True
    message.answer.assert_awaited_once_with(_USER_ERROR_TEXT)

    last_error = await db.get_last_event("error")
    assert last_error is not None
    assert last_error["details"].startswith("unhandled_error=ValueError: boom")

    records = _error_records(caplog)
    assert len(records) == 1


async def test_callback_query_message_is_answered(db: Database) -> None:
    callback = _registered_callback(db)
    message = MagicMock()
    message.answer = AsyncMock()
    callback_query = MagicMock()
    callback_query.message = message
    event = _make_event(callback_query=callback_query)

    result = await callback(event)

    assert result is True
    message.answer.assert_awaited_once_with(_USER_ERROR_TEXT)


async def test_reply_failure_does_not_break_handler(db: Database, caplog) -> None:
    callback = _registered_callback(db)
    message = MagicMock()
    message.answer = AsyncMock(side_effect=RuntimeError("network down"))
    event = _make_event(message=message)

    with caplog.at_level(logging.ERROR, logger="news_bot.bot.error_handler"):
        result = await callback(event)

    assert result is True
    last_error = await db.get_last_event("error")
    assert last_error is not None
    assert any(
        "error_reply_failed" in record.getMessage() for record in caplog.records
    )


async def test_db_write_failure_is_suppressed(db: Database) -> None:
    broken_db = MagicMock()
    broken_db.log_event = AsyncMock(side_effect=RuntimeError("db is closed"))
    callback = _registered_callback(broken_db)
    message = MagicMock()
    message.answer = AsyncMock()
    event = _make_event(message=message)

    result = await callback(event)

    assert result is True
    message.answer.assert_awaited_once_with(_USER_ERROR_TEXT)


async def test_update_without_message_is_tolerated(db: Database) -> None:
    callback = _registered_callback(db)
    event = _make_event(message=None, callback_query=None)

    result = await callback(event)

    assert result is True


async def test_error_details_truncated(db: Database) -> None:
    callback = _registered_callback(db)
    event = _make_event(exception=ValueError("x" * 1000))

    result = await callback(event)

    assert result is True
    last_error = await db.get_last_event("error")
    assert last_error is not None
    expected = "unhandled_error=" + f"ValueError: {'x' * 1000}"[:_MAX_ERROR_LEN]
    assert last_error["details"] == expected
    assert len(last_error["details"]) == len("unhandled_error=") + _MAX_ERROR_LEN
