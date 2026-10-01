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

1. Установите зависимости (в каталоге `news_bot/`):

```bash
uv sync
```

2. Создайте `.env` по примеру `.env.example` и заполните `BOT_TOKEN`, `CHANNEL_ID`.

3. Запустите — из родительского каталога (пакет импортируется как `news_bot`):

```bash
cd ..
news_bot/.venv/bin/python -m news_bot.main
```

Тесты (из каталога `news_bot/`):

```bash
uv run pytest
```

## Запуск через Docker Compose (разработка)

Из каталога `news_bot/`:

```bash
cp .env.example .env
docker compose up --build
```

## Production-деплой (VPS)

На сервере должны быть установлены Docker и compose-плагин. Первый запуск:

```bash
git clone <repo> newsbot && cd newsbot
mkdir -p data
# создайте .env (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS); TELEGRAM_PROXY не задавать
sudo chown -R 10001:10001 data   # uid контейнера appuser
docker compose up -d --build
docker compose logs -f newsbot
```

Обновление: `git pull && docker compose up -d --build`.

На production-сервере не задавайте `TELEGRAM_PROXY=127.0.0.1:...` — внутри контейнера это недоступно.

CI/CD (GitHub Actions: сборка образа, DockerHub, деплой по SSH) жил в родительском
репозитории Content Fabric; в этой автономной копии workflow нет — деплой вручную.

## Конфиг источников

`config/sources.yaml` содержит только несекретные данные:

- `settings.post_interval_hours`
- `settings.max_news_per_source`
- `settings.request_timeout`
- `filters.include_keywords`
- `filters.exclude_keywords`
- список `sources`

Секреты и runtime-настройки находятся в `.env`.
