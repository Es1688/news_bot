from __future__ import annotations

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, ErrorEvent, Message, Update

from news_bot.utils.db import Database
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)

_MAX_ERROR_LEN = 300
_USER_ERROR_TEXT = "Internal error occurred. Check /status later for details."


def register_error_handler(dispatcher: Dispatcher, db: Database) -> None:
    @dispatcher.errors()
    async def on_unhandled_error(event: ErrorEvent) -> bool:
        exc = event.exception
        error = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_LEN]
        logger.error("unhandled_error error=%s", error, exc_info=exc)

        try:
            await db.log_event("error", f"unhandled_error={error}")
        except Exception as db_exc:
            logger.error("error_event_write_failed error=%s", db_exc)

        message = _extract_message(event.update)
        if message is not None:
            try:
                await message.answer(_USER_ERROR_TEXT)
            except Exception as answer_exc:
                logger.error("error_reply_failed error=%s", answer_exc)
        return True


def _extract_message(update: Update) -> Message | None:
    if update.message is not None:
        return update.message
    callback: CallbackQuery | None = update.callback_query
    if callback is not None:
        return callback.message
    return None
