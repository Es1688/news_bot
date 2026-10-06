from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from news_bot.config.loader import AppConfig
from news_bot.core.factory import ContentFactory, FactoryResult
from news_bot.core.pipeline import Pipeline
from news_bot.utils.db import Database
from news_bot.utils.logging import get_logger


logger = get_logger(__name__)

_RETRACT_LOOKUP_LIMIT = 200
_RECENT_POSTS_LIMIT = 10
_LINE_TAIL_LIMIT = 80


def create_router(
    config: AppConfig,
    pipeline: Pipeline,
    db: Database,
    publish_lock: asyncio.Lock,
    started_at: datetime,
    *,
    factory: ContentFactory | None = None,
    factory_lock: asyncio.Lock | None = None,
    bot: Bot | None = None,
) -> Router:
    router = Router()

    def is_admin(message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else 0
        return user_id in config.admin_ids

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        uptime = datetime.now(timezone.utc) - started_at
        last_run = await db.get_last_event("run")
        last_error = await db.get_last_event("error")
        await message.answer(
            "\n".join(
                [
                    f"Uptime: {format_timedelta(uptime)}",
                    f"Last run: {format_event(last_run)}",
                    f"Last error: {format_event(last_error)}",
                ]
            )
        )

    @router.message(Command("sources"))
    async def sources_handler(message: Message) -> None:
        lines = []
        for source in config.sources:
            status = "enabled" if source.enabled else "disabled"
            category = f" ({source.category})" if source.category else ""
            lines.append(f"- {source.name}{category}: {status}")
        await message.answer("\n".join(lines) if lines else "No sources configured.")

    @router.message(Command("stats"))
    async def stats_handler(message: Message) -> None:
        stats = await db.get_daily_stats()
        if not stats:
            await message.answer("No stats yet.")
            return
        lines = ["Daily stats:"]
        for item in stats:
            lines.append(
                f"{item['day']}: publish={item['publishes']} errors={item['errors']}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("news"))
    async def news_handler(message: Message) -> None:
        if not is_admin(message):
            await message.answer("Access denied.")
            return
        async with publish_lock:
            await message.answer("Running pipeline...")
            result = await pipeline.run()
        await message.answer(
            f"Pipeline done: collected={result.collected} published={result.published}"
        )

    @router.message(Command("factory"))
    async def factory_handler(message: Message) -> None:
        if not is_admin(message):
            await message.answer("Access denied.")
            return

        args = (message.text or "").split()[1:]
        action = args[0].lower() if args else "run"

        if action == "run":
            if factory is None or factory_lock is None:
                await message.answer(
                    "Factory is disabled (check FACTORY_ENABLED / factory.enabled)."
                )
                return
            async with factory_lock:
                await message.answer("Running factory cycle...")
                result = await factory.run()
            await message.answer(format_factory_result(result))
            return

        if action == "pause":
            await db.set_state_flag("factory", False)
            await db.log_event("factory_pause", "manual")
            await message.answer("Factory paused. Use /factory resume to continue.")
            return

        if action == "resume":
            await db.set_state_flag("factory", True)
            await db.set_state_flag("factory_autopause", True)
            await db.log_event("factory_resume", "manual")
            await message.answer("Factory resumed (manual pause and auto-pause cleared).")
            return

        if action == "status":
            await message.answer(await factory_status(config, db))
            return

        if action == "retract":
            await retract_post(message, config, db, bot)
            return

        await message.answer(
            "Usage: /factory [run|pause|resume|status|retract <post_id>]"
        )

    @router.message(Command("posts"))
    async def posts_handler(message: Message) -> None:
        if not is_admin(message):
            await message.answer("Access denied.")
            return
        posts = await db.get_recent_posts(_RECENT_POSTS_LIMIT)
        if not posts:
            await message.answer("No posts yet.")
            return
        lines = ["Recent posts:"]
        for post in posts:
            tail = post.error or post.title or ""
            tail = " ".join(tail.split())
            lines.append(
                f"#{post.id} [{post.status}] attempts={post.attempts} "
                f"{post.source}: {tail[:_LINE_TAIL_LIMIT]}"
            )
        await message.answer("\n".join(lines))

    return router


async def factory_status(config: AppConfig, db: Database) -> str:
    paused = not await db.get_state_flag("factory")
    autopaused = not await db.get_state_flag("factory_autopause")
    last_run = await db.get_last_event("factory_run")
    lines = [
        f"Factory: {'enabled' if config.factory.enabled else 'disabled'} (config)",
        f"Dry-run: {'on' if config.factory.dry_run else 'off'}",
        f"Interval: {config.factory.interval_hours}h",
        f"Paused (manual): {'yes' if paused else 'no'}",
        f"Auto-paused: {'yes' if autopaused else 'no'}",
        f"Last cycle: {format_event(last_run)}",
    ]
    if autopaused:
        last_alert = await db.get_last_event("factory_alert")
        reason = (last_alert or {}).get("details") or "unknown"
        lines.append(f"Autopause reason: {_short(reason)}")
    return "\n".join(lines)


async def retract_post(
    message: Message, config: AppConfig, db: Database, bot: Bot | None
) -> None:
    args = (message.text or "").split()[1:]
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: /factory retract <post_id>")
        return
    post_id = int(args[1])

    posts = await db.get_recent_posts(_RETRACT_LOOKUP_LIMIT)
    post = next((p for p in posts if p.id == post_id), None)
    if post is None:
        await message.answer(f"Post {post_id} not found.")
        return
    if post.message_id is None or post.status == "previewed":
        await message.answer(
            "Cannot retract: the post has no channel message "
            "(dry-run previews go to the admins, not to the channel)."
        )
        return
    if bot is None:
        await message.answer("Retract is unavailable (bot instance missing).")
        return

    try:
        await bot.delete_message(config.channel_id, post.message_id)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        logger.error("factory_retract_failed id=%s error=%s", post_id, error)
        await message.answer(f"Retract failed: {error}")
        return
    await db.log_event("factory_retract", f"id={post_id}")
    await message.answer(f"Post {post_id} retracted from the channel.")


def format_factory_result(result: FactoryResult) -> str:
    return (
        "Factory cycle done: "
        f"collected={result.collected} filtered={result.filtered} "
        f"deduped={result.deduped} written={result.written} "
        f"skipped={result.skipped} published={result.published} "
        f"previewed={result.previewed} failed={result.failed} "
        f"recovered={result.recovered}"
    )


def format_event(event: dict | None) -> str:
    if not event:
        return "n/a"
    return f"{event['created_at']} ({_short(event.get('details') or 'no details')})"


def format_timedelta(delta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text[:limit]
