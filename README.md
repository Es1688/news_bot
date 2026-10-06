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

## Контент-фабрика

Помимо дайджеста ссылок, бот умеет работать как контент-фабрика: второй,
независимый цикл отбирает новости по своим ключевым словам, LLM переписывает их в
оригинальные посты и публикует в тот же Telegram-канал. Дайджест-цикл при этом не
меняется; у фабрики свой интервал, своя дедупликация и свои лимиты. Подробности —
в [ARCHITECTURE.md](ARCHITECTURE.md), раздел «Контент-фабрика».

Для включения заполните переменные в `news_bot/.env` (пример — `news_bot/.env.example`):

| Переменная | Назначение |
|---|---|
| `LLM_API_KEY` | ключ OpenAI-совместимого API; обязателен при включённой фабрике, только в `.env` |
| `LLM_BASE_URL` | базовый URL API (OpenAI, OpenRouter, vLLM/Ollama); переопределяет `factory.llm.base_url` |
| `LLM_MODEL` | имя модели; переопределяет `factory.llm.model` |
| `LLM_PROXY` | прокси для LLM-запросов (`socks5://…`/`http://…`); только для локального запуска при блокировке прямого IP провайдером, на VPS не задавать |
| `FACTORY_ENABLED` | включает/выключает фабрику; переопределяет `factory.enabled` из yaml |
| `FACTORY_INTERVAL_HOURS` | интервал цикла фабрики в часах; переопределяет `factory.interval_hours` |

Полный список ключей секции `factory` в `news_bot/config/sources.yaml`, команды
управления (`/factory run|pause|resume|status|retract`, `/posts`) и правила
включённости — в [news_bot/README.md](news_bot/README.md), раздел «Конфигурация
фабрики».

### Безопасная раскатка

Автопубликация включается только после раскатки; переход на следующий этап —
только при выполнении критериев предыдущего:

1. **Dry-run** (`factory.dry_run: true`): посты генерируются и уходят админам в
   личку, а не в канал. Критерии выхода: не менее 20 постов; владелец оценил бы
   ≥90% как «опубликовал бы»; 0 ложных срабатываний валидатора (проверяется по
   `rejected_text` отклонённых постов); 0 полностью неудачных циклов
   (`written == 0` и `failed > 0`).
2. **Тестовый канал**: `CHANNEL_ID` в `.env` указывает на тестовый канал; 2–3 дня
   с теми же критериями; `/factory retract` проверен вручную.
3. **Прод**: `posts_per_cycle: 1`, неделя без инцидентов — затем постепенное
   увеличение.
