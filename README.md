# Content Fabric — News Bot (MVP)

Репозиторий Telegram-бота, который собирает новости из RSS-источников (Habr, vc.ru),
фильтрует по ключевым словам, дедуплицирует в SQLite и публикует в Telegram-канал.

## Состав репозитория

- `news_bot/` — код бота (точка входа `news_bot/main.py`); детали — в
  [news_bot/README.md](news_bot/README.md)
- `infra/` — Docker Compose для продакшена (VPS)
- `.github/workflows/docker.yml` — CI/CD деплой на VPS из ветки `main`
- [ARCHITECTURE.md](ARCHITECTURE.md) — архитектурные решения

## Быстрый старт

Требуются [uv](https://docs.astral.sh/uv/) и Python 3.12+.

```bash
uv sync                                   # зависимости
cp news_bot/.env.example news_bot/.env    # заполнить BOT_TOKEN, CHANNEL_ID
uv run python -m news_bot.main            # запуск
uv run pytest                             # тесты
```

Запуск через Docker и деплой описаны в [news_bot/README.md](news_bot/README.md).
