from __future__ import annotations

import pytest

from news_bot.config.loader import load_config


@pytest.fixture
def env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("CHANNEL_ID", "-1001234567890")
    monkeypatch.setenv("ADMIN_IDS", "111,222,333")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.delenv("POST_INTERVAL_HOURS", raising=False)
    monkeypatch.delenv("REQUEST_TIMEOUT", raising=False)


def test_load_config_reads_yaml(env_vars: None) -> None:
    config = load_config()

    assert config.settings.max_news_per_source == 5
    assert config.filters.include_keywords == []
    assert config.filters.exclude_keywords == []
    assert len(config.sources) >= 1
    assert config.sources[0].name == "Python Insider"
    assert config.sources[0].type == "rss"
    assert config.sources[0].enabled is True


def test_env_overrides_yaml(env_vars: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POST_INTERVAL_HOURS", "12")
    monkeypatch.setenv("REQUEST_TIMEOUT", "45")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    config = load_config()

    assert config.settings.post_interval_hours == 12
    assert config.settings.request_timeout == 45
    assert config.log_level == "WARNING"


def test_missing_bot_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("CHANNEL_ID", "-1001234567890")

    with pytest.raises(ValueError, match="BOT_TOKEN and CHANNEL_ID are required"):
        load_config()


def test_missing_channel_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("CHANNEL_ID", "")

    with pytest.raises(ValueError, match="BOT_TOKEN and CHANNEL_ID are required"):
        load_config()


def test_admin_ids_parsed_from_comma_string(env_vars: None) -> None:
    config = load_config()

    assert config.admin_ids == [111, 222, 333]


def test_admin_ids_ignores_invalid_tokens(
    env_vars: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_IDS", "111, abc, 222, ,456")

    config = load_config()

    assert config.admin_ids == [111, 222, 456]


def test_empty_sources_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("CHANNEL_ID", "-1001234567890")
    monkeypatch.setattr(
        "news_bot.config.loader.yaml.safe_load",
        lambda _content: {"settings": {}, "filters": {}, "sources": []},
    )

    config = load_config()

    assert config.sources == []


def test_data_path_points_to_sqlite_file(env_vars: None) -> None:
    config = load_config()

    assert config.data_path.name == "news_bot.db"
    assert config.data_path.parent.name == "data"


def test_database_path_env_override(env_vars: None, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    custom_path = tmp_path / "custom.db"
    monkeypatch.setenv("DATABASE_PATH", str(custom_path))

    config = load_config()

    assert config.data_path == custom_path
