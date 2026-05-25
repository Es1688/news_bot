# Content Fabric News Bot (MVP)

Минимальный Telegram-бот для сборa RSS-новостей, фильтрации, дедупликации и публикации
в канал. Архитектура отделяет сбор новостей от публикации через интерфейс `Publisher`.

## Возможности

- RSS-only сбор новостей из `config/sources.yaml`
- keyword-фильтрация
- дедупликация в SQLite (`data/news_bot.db`)
- публикация в Telegram через `TelegramPublisher`
- базовые команды `/status`, `/sources`, `/stats`, `/news`

## Запуск локально

Требуется [uv](https://docs.astral.sh/uv/) и Python 3.12+.

1. Из корня репозитория установите зависимости:

```bash
uv sync
```

2. Создайте `news_bot/.env` по примеру `news_bot/.env.example` и заполните `BOT_TOKEN`, `CHANNEL_ID`.

3. Запустите:

```bash
uv run python -m news_bot.main
```

Тесты:

```bash
uv run pytest
```

## Запуск через Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

## Конфиг источников

`config/sources.yaml` содержит только несекретные данные:

- `settings.post_interval_hours`
- `settings.max_news_per_source`
- `settings.request_timeout`
- `filters.include_keywords`
- `filters.exclude_keywords`
- список `sources`

Секреты и runtime-настройки находятся в `.env`.
