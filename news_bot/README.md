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

## Запуск через Docker Compose (разработка)

Из каталога `news_bot/`:

```bash
cp .env.example .env
docker compose up --build
```

## Production-деплой

Из корня репозитория (имена контейнеров совпадают с VPS):

```bash
# Остановить локальный uv-процесс, если запущен — иначе конфликт getUpdates
pkill -f "news_bot.main" || true

# Подготовить news_bot/.env (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS)
docker compose -p newsbot -f infra/compose.prod.yml up -d --build
docker compose -p newsbot -f infra/compose.prod.yml logs -f newsbot
```

На VPS один раз создайте `/opt/newsbot/.env` и каталог `data/`:

```bash
sudo mkdir -p /opt/newsbot/data
# заполните /opt/newsbot/.env (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS)
sudo chown -R 10001:10001 /opt/newsbot/data   # uid контейнера appuser
```

CI/CD (push в `main`/`master`/`dev`) собирает образ, пушит в DockerHub и деплоит compose на VPS по SSH (base64, без scp). Права на `data/` выставляются автоматически через `alpine chown`.

Secrets GitHub Actions: `DOCKER_USERNAME`, `DOCKER_PASSWORD`, `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.  
Variables (опционально): `DOCKER_IMAGE_REPOSITORY` (по умолчанию `content-fabric-newsbot`), `VPS_APP_DIR` (по умолчанию `/opt/newsbot`).

На production-сервере не задавайте `TELEGRAM_PROXY=127.0.0.1:...` — внутри контейнера это недоступно.

## Конфиг источников

`config/sources.yaml` содержит только несекретные данные:

- `settings.post_interval_hours`
- `settings.max_news_per_source`
- `settings.request_timeout`
- `filters.include_keywords`
- `filters.exclude_keywords`
- список `sources`

Секреты и runtime-настройки находятся в `.env`.
