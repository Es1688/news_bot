from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import Command

from news_bot.bot.handlers import create_router
from news_bot.config.loader import AppConfig
from news_bot.core.factory import ContentFactory
from news_bot.core.models import Post
from news_bot.core.pipeline import Pipeline, PipelineResult
from news_bot.tests.mocks import (
    MockAlerter,
    MockFetcher,
    MockPostPublisher,
    MockPublisher,
    MockWriter,
)
from news_bot.utils.db import Database


def _command_name(handler) -> str | None:
    for filter_obj in handler.filters:
        callback = filter_obj.callback
        if isinstance(callback, Command):
            return callback.commands[0]
    return None


async def _invoke_command(router, command: str, user_id: int, text: str | None = None):
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.answer = AsyncMock()
    message.text = text or f"/{command.lstrip('/')}"

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


@pytest.fixture
def factory_setup(app_config: AppConfig, db: Database):
    fetcher = MockFetcher()
    publisher = MockPublisher()
    pipeline = Pipeline(app_config, fetcher, publisher, db)
    writer = MockWriter()
    post_publisher = MockPostPublisher()
    alerter = MockAlerter()
    factory = ContentFactory(app_config, fetcher, writer, post_publisher, alerter, db)
    publish_lock = asyncio.Lock()
    factory_lock = asyncio.Lock()
    bot = AsyncMock()
    bot.delete_message = AsyncMock(return_value=True)
    started_at = datetime.now(timezone.utc)
    router = create_router(
        app_config,
        pipeline,
        db,
        publish_lock,
        started_at,
        factory=factory,
        factory_lock=factory_lock,
        bot=bot,
    )
    return SimpleNamespace(
        router=router,
        pipeline=pipeline,
        factory=factory,
        writer=writer,
        bot=bot,
        db=db,
        app_config=app_config,
    )


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


# --- factory commands ---------------------------------------------------------


def _answers(message) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


def _make_post(**overrides) -> Post:
    fields: dict = dict(
        id=None,
        news_url="https://example.com/news/1",
        source="Test RSS",
        title="Python release improves compiler speed",
        text=None,
        status="draft",
    )
    fields.update(overrides)
    return Post(**fields)


@pytest.mark.asyncio
async def test_factory_run_allowed_for_admin(factory_setup) -> None:
    message = await _invoke_command(
        factory_setup.router, "factory", factory_setup.app_config.admin_ids[0], "/factory run"
    )

    texts = _answers(message)
    assert not any("Access denied" in text for text in texts)
    assert any("Factory cycle done:" in text for text in texts)


@pytest.mark.asyncio
async def test_factory_denied_for_non_admin(factory_setup) -> None:
    message = await _invoke_command(factory_setup.router, "factory", 999999)

    assert _answers(message) == ["Access denied."]
    assert factory_setup.writer.calls == []


@pytest.mark.asyncio
async def test_factory_pause_sets_flag(factory_setup) -> None:
    message = await _invoke_command(
        factory_setup.router, "factory", factory_setup.app_config.admin_ids[0], "/factory pause"
    )

    assert any("paused" in text.lower() for text in _answers(message))
    assert await factory_setup.db.get_state_flag("factory") is False


@pytest.mark.asyncio
async def test_factory_resume_clears_both_pauses(factory_setup) -> None:
    db = factory_setup.db
    await db.set_state_flag("factory", False)
    await db.set_state_flag("factory_autopause", False)

    message = await _invoke_command(
        factory_setup.router, "factory", factory_setup.app_config.admin_ids[0], "/factory resume"
    )

    assert await db.get_state_flag("factory") is True
    assert await db.get_state_flag("factory_autopause") is True
    assert any("resumed" in text.lower() for text in _answers(message))


@pytest.mark.asyncio
async def test_factory_status_shows_state(factory_setup) -> None:
    await factory_setup.db.set_state_flag("factory", False)
    await factory_setup.db.set_state_flag("factory_autopause", False)
    await factory_setup.db.log_event("factory_alert", "kind=config error=llm http 401")

    message = await _invoke_command(
        factory_setup.router, "factory", factory_setup.app_config.admin_ids[0], "/factory status"
    )

    texts = _answers(message)
    assert any("enabled" in text for text in texts)
    assert any("Paused (manual): yes" in text for text in texts)
    assert any("Auto-paused: yes" in text for text in texts)
    assert any("llm http 401" in text for text in texts)


@pytest.mark.asyncio
async def test_factory_retract_deletes_channel_message(factory_setup) -> None:
    post_id = await factory_setup.db.save_attempt(_make_post(status="draft"))
    await factory_setup.db.mark_post_published(post_id, 555)

    message = await _invoke_command(
        factory_setup.router,
        "factory",
        factory_setup.app_config.admin_ids[0],
        f"/factory retract {post_id}",
    )

    factory_setup.bot.delete_message.assert_awaited_once_with(
        factory_setup.app_config.channel_id, 555
    )
    assert any("retracted" in text for text in _answers(message))
    event = await factory_setup.db.get_last_event("factory_retract")
    assert event is not None
    assert f"id={post_id}" in event["details"]


@pytest.mark.asyncio
async def test_factory_retract_refuses_previewed_post(factory_setup) -> None:
    post_id = await factory_setup.db.save_attempt(_make_post(status="previewed"))

    message = await _invoke_command(
        factory_setup.router,
        "factory",
        factory_setup.app_config.admin_ids[0],
        f"/factory retract {post_id}",
    )

    factory_setup.bot.delete_message.assert_not_awaited()
    assert any("Cannot retract" in text for text in _answers(message))


@pytest.mark.asyncio
async def test_factory_retract_unknown_post(factory_setup) -> None:
    message = await _invoke_command(
        factory_setup.router,
        "factory",
        factory_setup.app_config.admin_ids[0],
        "/factory retract 12345",
    )

    factory_setup.bot.delete_message.assert_not_awaited()
    assert any("not found" in text for text in _answers(message))


@pytest.mark.asyncio
async def test_posts_lists_recent_posts(factory_setup) -> None:
    await factory_setup.db.save_attempt(
        _make_post(status="published", news_url="https://example.com/a")
    )
    await factory_setup.db.save_attempt(
        _make_post(
            status="failed",
            news_url="https://example.com/b",
            error="llm http 429",
        )
    )

    message = await _invoke_command(
        factory_setup.router, "posts", factory_setup.app_config.admin_ids[0]
    )

    texts = _answers(message)
    assert any("published" in text for text in texts)
    assert any("failed" in text for text in texts)
    assert any("llm http 429" in text for text in texts)


@pytest.mark.asyncio
async def test_posts_denied_for_non_admin(factory_setup) -> None:
    message = await _invoke_command(factory_setup.router, "posts", 999999)

    assert _answers(message) == ["Access denied."]


@pytest.mark.asyncio
async def test_posts_empty_answers_politely(factory_setup) -> None:
    message = await _invoke_command(
        factory_setup.router, "posts", factory_setup.app_config.admin_ids[0]
    )

    assert any("No posts yet" in text for text in _answers(message))
