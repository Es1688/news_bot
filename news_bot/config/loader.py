from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class SourceConfig:
    name: str
    type: str
    url: str
    enabled: bool
    category: str | None = None


@dataclass(frozen=True)
class AppSettings:
    post_interval_hours: int
    max_news_per_source: int
    request_timeout: int


@dataclass(frozen=True)
class FilterSettings:
    include_keywords: list[str]
    exclude_keywords: list[str]


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    channel_id: str
    admin_ids: list[int]
    log_level: str
    settings: AppSettings
    filters: FilterSettings
    sources: list[SourceConfig]
    data_path: Path


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _parse_sources(raw: list[dict[str, Any]]) -> list[SourceConfig]:
    sources: list[SourceConfig] = []
    for item in raw:
        sources.append(
            SourceConfig(
                name=str(item.get("name", "")).strip(),
                type=str(item.get("type", "")).strip(),
                url=str(item.get("url", "")).strip(),
                enabled=bool(item.get("enabled", False)),
                category=item.get("category"),
            )
        )
    return sources


def load_config() -> AppConfig:
    load_dotenv()
    config_dir = Path(__file__).resolve().parent
    config_path = config_dir / "sources.yaml"
    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    settings = raw_config.get("settings", {})
    filters = raw_config.get("filters", {})
    sources = raw_config.get("sources", [])

    post_interval_hours = _env_int(
        "POST_INTERVAL_HOURS", int(settings.get("post_interval_hours", 6))
    )
    request_timeout = _env_int(
        "REQUEST_TIMEOUT", int(settings.get("request_timeout", 30))
    )

    app_settings = AppSettings(
        post_interval_hours=post_interval_hours,
        max_news_per_source=int(settings.get("max_news_per_source", 5)),
        request_timeout=request_timeout,
    )
    filter_settings = FilterSettings(
        include_keywords=[str(x) for x in filters.get("include_keywords", [])],
        exclude_keywords=[str(x) for x in filters.get("exclude_keywords", [])],
    )

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    channel_id = os.getenv("CHANNEL_ID", "").strip()
    admin_raw = os.getenv("ADMIN_IDS", "").strip()
    log_level = os.getenv("LOG_LEVEL", "INFO").strip()

    if not bot_token or not channel_id:
        raise ValueError("BOT_TOKEN and CHANNEL_ID are required")

    admin_ids = [
        int(value)
        for value in admin_raw.split(",")
        if value.strip().isdigit()
    ]

    data_env = os.getenv("DATABASE_PATH", "").strip()
    if data_env:
        data_path = Path(data_env)
    else:
        data_path = config_dir.parent / "data" / "news_bot.db"

    return AppConfig(
        bot_token=bot_token,
        channel_id=channel_id,
        admin_ids=admin_ids,
        log_level=log_level,
        settings=app_settings,
        filters=filter_settings,
        sources=_parse_sources(sources),
        data_path=data_path,
    )
