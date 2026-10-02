# AGENTS.md — content-fabric

## Что это за проект
Telegram-бот (MVP), собирающий новости из RSS-источников (Habr, vc.ru), фильтрующий их
по ключевым словам, дедуплицирующий в SQLite и публикующий в Telegram-канал. Стек:
Python 3.12, aiogram 3, aiohttp + feedparser, SQLite; зависимости — uv, тесты — pytest.
Деплой: Docker Compose на VPS через GitHub Actions (`.github/workflows/docker.yml`).

## Структура
| Путь | Что это | Можно менять? |
|---|---|---|
| `news_bot/main.py` | Точка входа бота | да |
| `news_bot/bot/` | Хендлеры и планировщик aiogram | да |
| `news_bot/parsers/` | RSS-парсеры источников (стратегия `base.py`) | да |
| `news_bot/publishers/` | Публикация (интерфейс `base.py`, Telegram) | да |
| `news_bot/core/` | Модели и пайплайн обработки | да |
| `news_bot/utils/` | БД, фильтры, форматтер, логирование | да |
| `news_bot/config/sources.yaml` | Список RSS-источников | да |
| `news_bot/data/` | Рабочая SQLite-БД (в git не коммитится) | нет (gitignore) |
| `news_bot/tests/` | pytest-тесты | да |
| `infra/` | Compose-файлы продакшена (VPS) | да |
| `.github/workflows/` | CI/CD деплой на VPS | да |
| `ARCHITECTURE.md` | Архитектурные решения | docs-only |

## Ключевые правила
- MVP работает только на RSS-источниках; отказ от парсинга HTML — архитектурное решение
  (см. `ARCHITECTURE.md`), откат — только через ADR.
- Секреты (`BOT_TOKEN`, `CHANNEL_ID` и пр.) — только в `.env`; в git не попадают.
- Результат валидируется: `uv run pytest` из корня репозитория.

## Соглашения
- Язык: код и коммиты — английский; документация — русский.
- Деплой/пуш — только с подтверждения пользователя (Level 0 + project.yaml).
