from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import Command

from news_bot.bot.handlers import create_router
from news_bot.config.loader import AppConfig
from news_bot.core.pipeline import Pipeline, PipelineResult
from news_bot.tests.mocks import MockFetcher, MockPublisher
from news_bot.utils.db import Database


def _command_name(handler) -> str | None:
    for filter_obj in handler.filters:
        callback = filter_obj.callback
        if isinstance(callback, Command):
            return callback.commands[0]
    return None


async def _invoke_command(router, command: str, user_id: int):
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.answer = AsyncMock()

    for handler in router.message.handlers:
        if _command_name(handler) == command.lstrip("/"):
            await handler.callback(message)
            return message
    raise AssertionError(f"Handler for /{command.lstrip('/')} not found")


@pytest.fixture
def handler_setup(app_config: AppConfig, db: Database):
    fetcher = MockFetcher()
    publisher = MockPublisher()
    pipeline = Pipeline(app_config, fetcher, publisher, db)
    publish_lock = asyncio.Lock()
    started_at = datetime.now(timezone.utc)
    router = create_router(app_config, pipeline, db, publish_lock, started_at)
    return router, pipeline, publish_lock, db, app_config


@pytest.mark.asyncio
async def test_news_allowed_for_admin(handler_setup) -> None:
    router, pipeline, _, _, app_config = handler_setup

    with patch.object(
        pipeline,
        "run",
        new=AsyncMock(
            return_value=PipelineResult(collected=1, filtered=1, published=1, skipped=0)
        ),
    ) as mock_run:
        message = await _invoke_command(router, "news", app_config.admin_ids[0])

    mock_run.assert_awaited_once()
    texts = [call.args[0] for call in message.answer.await_args_list]
    assert not any("Access denied" in text for text in texts)


@pytest.mark.asyncio
async def test_news_denied_for_non_admin(handler_setup) -> None:
    router, pipeline, _, _, _ = handler_setup

    with patch.object(pipeline, "run", new=AsyncMock()) as mock_run:
        message = await _invoke_command(router, "news", 999999)

    mock_run.assert_not_awaited()
    texts = [call.args[0] for call in message.answer.await_args_list]
    assert texts == ["Access denied."]


@pytest.mark.asyncio
async def test_status_command_responds(handler_setup, db: Database) -> None:
    router, _, _, _, _ = handler_setup
    await db.log_event("run", "collected=1")

    message = await _invoke_command(router, "status", 999999)

    texts = [call.args[0] for call in message.answer.await_args_list]
    assert any("Uptime:" in text for text in texts)


@pytest.mark.asyncio
async def test_sources_command_lists_sources(handler_setup) -> None:
    router, _, _, _, _ = handler_setup

    message = await _invoke_command(router, "sources", 999999)

    texts = [call.args[0] for call in message.answer.await_args_list]
    assert any("Test RSS" in text for text in texts)


@pytest.mark.asyncio
async def test_stats_command_responds(handler_setup, db: Database) -> None:
    router, _, _, _, _ = handler_setup
    await db.log_event("publish", "published=1")

    message = await _invoke_command(router, "stats", 999999)

    assert message.answer.await_count >= 1
