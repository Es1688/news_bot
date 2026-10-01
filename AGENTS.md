# AGENTS.md — news-bot

## Что это за проект
Telegram-бот (MVP): собирает RSS-новости из `config/sources.yaml`, фильтрует по
ключевым словам, дедуплицирует в SQLite и публикует в Telegram-канал.
Стек: Python 3.12, aiogram 3, feedparser, SQLite. Проект — часть Content Fabric;
здесь лежит автономная копия пакета `news_bot` (Dockerfile и README рассчитаны
на сборку из корня родительского репозитория, где находятся `pyproject.toml`
и `uv.lock` — в этой копии их нет).

## Структура
| Путь | Что это | Можно менять? |
|---|---|---|
| `main.py` | точка входа: Bot, Dispatcher, scheduler | да |
| `bot/` | хендлеры команд и scheduler-луп | да |
| `core/` | модели данных и pipeline (fetch → filter → dedup → publish) | да |
| `parsers/` | фетчеры источников (rss, vc_ru, composite) | да |
| `publishers/` | протокол `Publisher` и TelegramPublisher | да |
| `config/` | загрузчик конфига и несекретный `sources.yaml` | да |
| `utils/` | db (SQLite), filters, formatter, logging | да |
| `tests/` | pytest-тесты | да |
| `scripts/` | healthcheck | да |
| `data/` | runtime-данные; `*.db` в git не попадает | нет (runtime) |
| `.env` | секреты (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS) | нет, не коммитится |

## Ключевые правила
- Секреты — только в `.env` (создаётся по примеру `.env.example`);
  `config/sources.yaml` содержит только несекретные данные.
- Сбор новостей отделён от публикации через интерфейс `Publisher` —
  новые каналы публикации реализуются этим интерфейсом.
- Проверка изменений: `.venv/bin/python -m pytest`.

## Соглашения
- Язык: код и коммиты — английский; документация — русский.
- Деплой/пуш — только с подтверждения пользователя (Level 0 + project.yaml).
