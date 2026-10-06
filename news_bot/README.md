# Content Fabric News Bot (MVP)

Минимальный Telegram-бот для сборa RSS-новостей, фильтрации, дедупликации и публикации
в канал. Архитектура отделяет сбор новостей от публикации через интерфейс `Publisher`.

## Возможности

- RSS-only сбор новостей из `config/sources.yaml`
- keyword-фильтрация
- дедупликация в SQLite (`data/news_bot.db`)
- публикация в Telegram через `TelegramPublisher`
- контент-фабрика: LLM переписывает отобранные новости в посты и публикует их
  (второй цикл; стартует в dry-run — посты уходят админам, а не в канал)
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

CI/CD (push в `main`) собирает образ, пушит в DockerHub и деплоит compose на VPS по SSH (base64, без scp). Права на `data/` выставляются автоматически через `alpine chown`.

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

## Конфигурация фабрики

Контент-фабрика — второй цикл бота: LLM переписывает отобранные новости в
оригинальные посты и публикует их в тот же канал. Дайджест продолжает работать
как раньше; у фабрики свой интервал, свои ключевые слова отбора, своя
дедупликация и свои лимиты. Архитектура, машина состояний и классы ошибок — в
[ARCHITECTURE.md](../ARCHITECTURE.md), раздел «Контент-фабрика».

### Секция `factory` в `config/sources.yaml`

```yaml
factory:
  enabled: false         # старт выключен: включение — FACTORY_ENABLED=true в .env (+ LLM_API_KEY)
  dry_run: true          # безопасный старт: посты уходят админам, не в канал
  interval_hours: 4
  posts_per_cycle: 1
  max_posts_per_day: 10
  max_attempts: 3
  stale_draft_minutes: 30
  max_news_age_hours: 24
  max_post_chars: 1800
  active_hours: "08:00-23:00"
  timezone: "Europe/Moscow"
  alert_after_failed_cycles: 3
  circuit_breaker_after: 3
  max_news_per_source: 5
  include_keywords: []
  exclude_keywords: []
  llm:
    base_url: "https://api.openai.com/v1"
    model: "gpt-4o-mini"
    timeout: 60
    max_tokens: 2000
    temperature: 0.7
    disable_reasoning: false  # true — для «думающих» моделей (qwen3 и т.п.)
  prompt: |
    Ты — редактор Telegram-канала ...
    (полный рабочий текст промпта — в самом sources.yaml)
```

Значения выше — рабочий пример; актуальные значения по умолчанию — в самом
`config/sources.yaml`. Назначение ключей:

| Ключ | Назначение |
|---|---|
| `enabled` | базовый флаг включённости (может быть перекрыт env `FACTORY_ENABLED`) |
| `dry_run` | режим превью: посты отправляются админам, статус `previewed`, в канал не уходят |
| `interval_hours` | интервал цикла фабрики; не зависит от `settings.post_interval_hours` дайджеста |
| `posts_per_cycle` | максимум постов за один цикл (recovery тоже занимает место) |
| `max_posts_per_day` | суточный лимит попыток; считается по `last_attempt_at` — ретраи тоже расходуют LLM-вызовы |
| `max_attempts` | максимум контентных неудач на пост; после — `failed` терминально |
| `stale_draft_minutes` | `draft` старше этого возраста публикуется повторно в начале цикла (без вызова LLM) |
| `max_news_age_hours` | допустимый возраст новости по `published_at`; защита от бэклога лент при первом запуске; новости без даты в отбор не попадают |
| `max_post_chars` | мягкий потолок длины поста по видимому тексту (читабельность канала); жёсткий предел Telegram — 4096 |
| `active_hours` | окно публикации «ЧЧ:ММ-ЧЧ:ММ»; вне окна цикл пишет heartbeat-событие idle |
| `timezone` | часовой пояс для `active_hours` (имя zoneinfo, например `Europe/Moscow`) |
| `alert_after_failed_cycles` | сколько подряд «неудачных циклов» (`written == 0` и `failed > 0`) набирается до алерта админам |
| `circuit_breaker_after` | сколько подряд инфраструктурных ошибок прерывают цикл (экономия токенов; без штрафа по attempts) |
| `max_news_per_source` | максимум новостей от одного источника в цикле |
| `include_keywords` / `exclude_keywords` | ключевые слова отбора фабрики — отдельно от `filters` дайджеста |
| `llm.base_url` | базовый URL OpenAI-совместимого API (OpenAI, OpenRouter, vLLM/Ollama) |
| `llm.model` | имя модели |
| `llm.timeout` | таймаут запроса к LLM, секунды |
| `llm.max_tokens` | лимит токенов ответа |
| `llm.temperature` | температура генерации |
| `llm.disable_reasoning` | `true` — отключить «размышления» модели (параметр OpenRouter `reasoning.enabled=false`). Нужен для думающих моделей (например, qwen3): без него модель может израсходовать весь `max_tokens` на reasoning и вернуть пустой ответ (`content=null`) |
| `prompt` | system-prompt писателя (русский): данные новости в разделителях `<article>…</article>`, запрет выполнять инструкции из текста статьи, запрет выводить ссылки, право вернуть маркер `SKIP` для нерелевантного материала |

### Переменные окружения фабрики

| Переменная | Назначение |
|---|---|
| `LLM_API_KEY` | ключ OpenAI-совместимого API; только в `.env`, в yaml его нет; включённая фабрика без ключа — ошибка старта |
| `LLM_BASE_URL` | переопределяет `factory.llm.base_url`, если задана |
| `LLM_MODEL` | переопределяет `factory.llm.model`, если задана |
| `LLM_PROXY` | прокси для LLM-запросов (`socks5://…`/`http://…`), env-only; пустая — напрямую. Нужна только локально, когда провайдер блокирует прямой IP; RSS-сбор всегда идёт напрямую |
| `FACTORY_ENABLED` | переопределяет `factory.enabled`, если задана |
| `FACTORY_DRY_RUN` | dry-run фабрики (`true`/`false`): `true` — превью админам, `false` — публикация в канал; переопределяет `factory.dry_run`, если задана. На VPS — штатный переключатель раскатки (после смены — пересоздать контейнер `docker compose up -d`, `docker restart` не перечитывает `env_file`) |
| `FACTORY_INTERVAL_HOURS` | переопределяет `factory.interval_hours`, если задана |
| `FACTORY_ACTIVE_HOURS` | окно активности для docker-healthcheck (дефолт `08:00-23:00`); сравнивается с локальным временем контейнера (обычно UTC) — сама фабрика использует `factory.timezone` |

Единое правило включённости: фабрика работает, если
`(FACTORY_ENABLED, если задана, иначе factory.enabled)` И нет ручной паузы
(`/factory pause`) И нет авто-паузы после сбоя конфига/доступа — последняя
снимается `/factory resume`.

### Команды бота

| Команда | Назначение |
|---|---|
| `/status` | краткое состояние бота: uptime, последний запуск, ошибки |
| `/sources` | список RSS-источников и их статус |
| `/stats` | статистика публикаций за последние дни |
| `/news` | ручной запуск сбора и публикации дайджеста (админ) |
| `/factory run` | ручной запуск цикла фабрики (админ) |
| `/factory pause` | пауза фабрики: флаг в БД, без редеплоя (админ) |
| `/factory resume` | снятие паузы, включая авто-паузу после сбоя конфига/доступа (админ) |
| `/factory status` | состояние фабрики и причина остановки: paused / autopause с кодом ошибки (админ) |
| `/factory retract <id>` | удаление поста из канала по `message_id` (админ) |
| `/posts` | последние посты фабрики: статус, попытки, обрезанные ошибки (админ) |
