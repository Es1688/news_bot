# Architecture — Content Fabric News Bot

Небольшой production-бот для сбора новостей из RSS-источников и публикации в Telegram-канал.
Проект должен оставаться простым: сначала автономный Telegram-бот, затем аккуратное встраивание в систему фабрики контента.

Главный принцип: отделить сбор и подготовку новости от способа публикации. Сегодня выходом является Telegram, позже тем же ядром сможет пользоваться фабрика контента.

Контент-фабрика реализована внутри этого же бота — как второй параллельный цикл; см. раздел «Контент-фабрика».

---

## Цели

- Собрать MVP, который можно запустить в Docker и оставить работать без ручного присмотра.
- Использовать RSS как основной и единственный источник на первом этапе.
- Хранить состояние дедупликации в SQLite, чтобы не публиковать одну новость дважды.
- Дать минимальное управление через Telegram-команды.
- Заложить простой контракт `NewsItem` и `Publisher`, чтобы позже заменить или дополнить Telegram-публикацию интеграцией с фабрикой контента.

## Не цели на MVP

- HTML-парсинг сайтов.
- Извлечение `og:image`, сложные превью и обогащение карточек.
- PostgreSQL, очереди, Celery, Kafka, web admin panel.
- Микросервисная архитектура.
- Сложная система ролей.

Эти вещи можно добавить позже, когда RSS-only бот стабильно работает.

---

## Путь развития

### 1. MVP

Минимальный бот:

- читает RSS-источники из `config/sources.yaml`;
- нормализует записи в `NewsItem`;
- фильтрует новости по ключевым словам;
- проверяет дедупликацию в SQLite;
- публикует новые новости в Telegram;
- запускается через Docker Compose;
- пишет логи в stdout и события в SQLite.

### 2. Надежность

После работающего MVP добавляются production-мелочи без усложнения архитектуры:

- retries/backoff для сетевых запросов;
- `asyncio.Lock` на цикл публикации, чтобы scheduler и ручная команда не запускали сбор одновременно;
- admin whitelist через `ADMIN_IDS`;
- healthcheck для Docker;
- ротация или аккуратный вывод логов;
- базовые тесты для конфигурации, фильтрации, дедупликации и форматирования.

### 3. Управление

Команды бота:

| Команда | Назначение |
|---|---|
| `/status` | краткое состояние бота: uptime, последний запуск, ошибки |
| `/sources` | список RSS-источников и их статус |
| `/stats` | статистика публикаций за последние дни |
| `/news` | ручной запуск сбора и публикации, только для админа |

Изменение источников через команды можно добавить позже. Для начала источники правятся в `sources.yaml`, так проще и безопаснее.

### 4. Контент-фабрика (реализовано; иначе, чем в эскизе)

Изначально здесь был эскиз: `ContentFactoryPublisher` передаёт `NewsItem` во внутренний
API, webhook или очередь внешней фабрики, ядро сбора новостей не меняется.
Реализовано иначе — прямым параллельным циклом `ContentFactory` в том же процессе:

- `TelegramPublisher` продолжает отправлять новости в канал (дайджест-цикл);
- фабрика — второй цикл «поиск → LLM-написание поста → автопубликация» со своим
  интервалом, своей дедупликацией и своими лимитами, публикует в тот же канал;
- переиспользуются общие строительные блоки: `Fetcher` (RSS-сбор), `NewsItem`
  и одна `aiohttp.ClientSession` на процесс.

Почему не ветка `Publisher`: фабрика — не «другой транспорт для новости», а другой
продукт (свой отбор, машина состояний posts, LLM-писатель с валидацией и лимитами);
её требования не влезают в `Publisher.publish(items)` без раздувания контракта
дайджеста. Подробности — в разделе «Контент-фабрика».

### 5. HTML и preview

HTML-парсинг и preview-обогащение добавляются только после стабильного RSS-пайплайна:

- `HtmlFetcher` для сайтов без RSS;
- извлечение `og:title`, `og:description`, `og:image`;
- дополнительные лимиты и таймауты, чтобы preview не тормозил публикацию.

---

## Архитектура MVP

```
RSS-источники
      |
      v
RssFetcher
      |
      v
NewsItem[]
      |
      v
KeywordFilter
      |
      v
Deduplicator / SQLite
      |
      v
PostFormatter
      |
      v
Publisher
      |
      +--> TelegramPublisher
```

Ключевая идея: `Publisher` является границей между ядром бота и внешней системой публикации.

Это поток дайджест-цикла. Контент-фабрика — второй, параллельный цикл (см. «Контент-фабрика»).

---

## Структура проекта

```
news_bot/
├── bot/
│   ├── handlers.py          # команды Telegram (дайджест + фабрика)
│   └── scheduler.py         # два шедулер-цикла: дайджест и фабрика
│
├── config/
│   ├── loader.py            # YAML + .env (settings, filters, factory)
│   ├── sources.yaml         # RSS-источники и настройки
│   └── __init__.py
│
├── core/
│   ├── models.py            # NewsItem, Post, PublishedResult
│   ├── pipeline.py          # дайджест: fetch -> filter -> dedupe -> publish
│   ├── factory.py           # цикл контент-фабрики (без aiogram)
│   └── __init__.py
│
├── parsers/
│   ├── base.py              # интерфейс fetcher
│   ├── rss.py               # RSS/Atom fetcher (+ summary, общая сессия)
│   └── __init__.py
│
├── publishers/
│   ├── base.py              # интерфейс Publisher (дайджест)
│   ├── telegram.py          # публикация в Telegram (дайджест)
│   ├── post.py              # PostPublisherProtocol + PostPublisher (фабрика)
│   ├── alerter.py           # Alerter + TelegramAlerter (алерты админам)
│   └── __init__.py
│
├── writers/
│   ├── base.py              # Writer-протокол + WriteResult
│   ├── llm.py               # LlmWriter (OpenAI-совместимый API)
│   ├── validator.py         # валидация вывода LLM
│   └── __init__.py
│
├── utils/
│   ├── db.py                # SQLite, миграции user_version, дедуп, статистика
│   ├── text.py              # canonical_url, title_tokens, jaccard
│   ├── sanitize.py          # санитайзер Telegram-HTML
│   ├── filters.py           # keyword-фильтрация
│   ├── formatter.py         # Telegram-текст
│   └── logging.py           # настройка логирования
│
├── scripts/
│   └── healthcheck.py       # Docker healthcheck (дайджест + фабрика)
│
├── data/
│   └── news_bot.db          # Docker volume
│
├── tests/
│   ├── test_filters.py      # фильтры дайджеста
│   ├── test_loader.py       # конфиг + env-оверрайды
│   ├── test_pipeline.py     # дайджест-пайплайн
│   ├── test_formatter.py    # форматтер Telegram
│   ├── test_handlers.py     # команды бота
│   ├── test_architecture.py # инварианты (без aiogram, бан зависимостей)
│   ├── test_db.py           # миграции, UPSERT, флаги, stale drafts
│   ├── test_text.py         # канонизация URL, токены, Jaccard
│   ├── test_rss.py          # RSS (+ @pytest.mark.network)
│   ├── test_factory.py      # цикл фабрики
│   ├── test_llm_writer.py   # LlmWriter на локальном тест-сервере
│   ├── test_validator.py    # валидатор
│   └── test_sanitize.py     # санитайзер («злые» кейсы)
│
├── main.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

Структура чуть шире минимальной, но каждый слой имеет понятную причину. Главное — не добавлять абстракции глубже этих границ, пока они реально не понадобятся.

---

## Модель данных

Единая модель новости нужна для того, чтобы парсеры, фильтры, дедупликация, Telegram и будущая фабрика говорили на одном языке.

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: datetime | None = None
    category: str | None = None
    summary: str | None = None
```

`summary` — очищенный от HTML текст RSS-описания (обрезка ~1000 символов): фабрика
отдаёт его LLM как исходный материал.

Для фабрики добавлена модель `Post` — состояние поста в таблице `posts`
(см. «Машина состояний posts» в разделе «Контент-фабрика»).

Для MVP достаточно `dataclass`. `pydantic` можно добавить позже, если появится внешний API или строгая валидация payload для фабрики.

---

## Publisher

Публикация должна быть отдельным интерфейсом, а не частью парсера или scheduler.

```python
from typing import Protocol


class Publisher(Protocol):
    async def publish(self, items: list[NewsItem]) -> PublishedResult:
        ...
```

На первом этапе реализуется только `TelegramPublisher`. Эскизная идея `ContentFactoryPublisher` не понадобилась: фабрика контента реализована параллельным циклом (см. «Контент-фабрика»), а `Publisher` остаётся контрактом дайджест-пайплайна.

Это не усложняет MVP, но защищает проект от переписывания, когда бот станет частью фабрики контента.

---

## Поток одного цикла дайджеста

```
scheduler.py или /news
  |
  v
Pipeline.run()
  |
  +--> загрузить enabled RSS-источники
  +--> RssFetcher.fetch(source)
  +--> привести записи к NewsItem
  +--> KeywordFilter.passes(item)
  +--> db.is_sent(item.url)
  +--> Publisher.publish(items)
  +--> db.mark_sent(item.url)
  +--> db.log_event(...)
```

Важное правило: помечать новость как отправленную только после успешной публикации. Иначе можно потерять новость при ошибке Telegram API.

Для защиты от двойного запуска используется один lock:

```python
publish_lock = asyncio.Lock()

async with publish_lock:
    await pipeline.run()
```

У фабрики — свой отдельный `asyncio.Lock` с тем же назначением: циклы не блокируют
друг друга. Общие при этом ресурсы (Telegram-лимиты, одна SQLite) — см. «Раздельные
локи, общие ресурсы» в разделе «Контент-фабрика».

---

## Контент-фабрика

Фабрика — второй независимый цикл бота: «поиск информации → написание поста (LLM) →
автопубликация в тот же Telegram-канал». Дайджест-пайплайн при этом не меняется:
у фабрики свой интервал, свой `asyncio.Lock`, свой отбор (ключевые слова и возраст
новостей), своя дедупликация и свои лимиты. Оба цикла живут в одном процессе,
публикуют в один канал одним ботом и пишут в одну SQLite-базу.

Автопубликация включается только после раскатки через dry-run с числовыми
критериями выхода (сценарий — в README).

### Стадии цикла

```
factory_scheduler_loop (свой интервал, свой asyncio.Lock)
  |
  v
проверка паузы и тихих часов --- вне окна / пауза ---> heartbeat-событие idle
  |                                                     (factory_run, JSON)
  v
recovery: draft старше stale_draft_minutes публикуется повторно
  |        (текст уже в БД, LLM не вызывается; входит в оба лимита)
  v
RSS-источники (те же, что у дайджеста) -> RssFetcher (общая ClientSession)
  |
  v
фильтр ключей фабрики (factory.include/exclude_keywords)
  |
  v
age-фильтр: max_news_age_hours по published_at (новость без даты — мимо отбора)
  |
  v
канонизация URL: срезать utm_*/fbclid и фрагмент, убрать trailing slash,
  |             хост в нижнем регистре
  v
дедупликация:
  +-- posts: статус draft | published | previewed | skipped,
  |           либо failed с attempts >= max_attempts
  +-- Jaccard заголовков >= ~0.7: посты за 7 дней + внутри пачки цикла
  |
  v
лимиты: posts_per_cycle и max_posts_per_day (по last_attempt_at)
  |
  v
LlmWriter: новость в разделителях <article>...</article>,
  |         анти-инъекция, запрет выводить ссылки, право вернуть SKIP
  v
валидатор: без URL; видимая длина ~200..max_post_chars (жёсткий предел 4096);
  |         без отказ-фраз ("As an AI...")
  v
санитайзер: whitelist <b> <i> <a href>, остальное через html.escape;
  |          href только http/https; несбалансированные теги -> fallback
  v
PostPublisher: TelegramRetryAfter (спать retry_after, повторить),
  |            пауза ~2-3 с между постами; ссылку на источник добавляет код;
  |            dry-run -> админам, message_id NULL
  v
mark_post_published(message_id) / mark_post_failed(error) / skipped (терминальный)
```

### Границы архитектуры

`core/factory.py` не импортирует aiogram — как и `core/pipeline.py` (проверяется
тестом архитектуры). Вся Telegram-специфика спрятана за протоколами:

```python
# writers/base.py
@dataclass(frozen=True)
class WriteResult:
    status: str              # "written" | "skipped" | "error"
    post: Post | None
    error_kind: str | None   # "content" | "infra" | "config"
    error: str | None        # обрезан ~300, без заголовков и ключей
    tokens: int = 0
    latency_ms: int = 0


class Writer(Protocol):
    async def write_post(self, item: NewsItem) -> WriteResult: ...


# publishers/post.py
class PostPublisherProtocol(Protocol):
    async def publish_post(self, post: Post, *, to_admins: bool = False) -> PostPublishResult: ...


# publishers/alerter.py
class Alerter(Protocol):
    async def send_alert(self, text: str) -> None: ...
    async def send_recovery(self, text: str) -> None: ...
```

- `WriteResult` явно различает успех, SKIP (материал нерелевантен или скуден) и
  ошибку с её классом, и несёт usage (токены, латентность) для счётчиков.
- `LlmWriter` ходит в OpenAI-совместимый API (`base_url` + `model`; совместим с
  OpenAI, OpenRouter, vLLM/Ollama) на уже имеющемся aiohttp — новых
  pip-зависимостей нет.
- Один общий `aiohttp.ClientSession` на процесс передаётся в `RssFetcher` и
  `LlmWriter` и закрывается при shutdown.

### Машина состояний posts

Таблица `posts` (миграция v2): `news_url` UNIQUE (канонический URL), `status`,
`text` (nullable), `attempts`, `error`, `prompt_version`, `llm_model`, `tokens`,
`message_id`, `rejected_text`, `created_at`, `published_at`, `last_attempt_at`.

| Статус | Что значит | Переходы |
|---|---|---|
| `draft` | текст сгенерирован, отправка ещё не подтверждена | → `published` / `previewed` / `failed` |
| `published` | отправлен в канал, сохранён `message_id` | терминальный |
| `previewed` | dry-run: отправлен админам, `message_id` NULL | терминальный; для healthcheck/алертов — успех |
| `failed` | зафиксирована ошибка обработки | рерайт в следующих циклах, пока `attempts < max_attempts` |
| `skipped` | LLM вернул маркер SKIP (материал нерелевантен/скуден) | терминальный, не ретраится |

Правила:

- Строка posts создаётся при любой **обработанной** ошибке (LLM, валидация,
  отправка) — чтобы вёлся счётчик attempts; колонка `text` nullable, у строк
  ошибок текста может не быть. При `CancelledError` строка не создаётся: отмена
  таска — не попытка, «зависший» draft ловит recovery.
- `attempts` инкрементируют только контентные ошибки; после `max_attempts` (3)
  пост остаётся `failed` и в отбор больше не попадает.
- `last_attempt_at` обновляется при каждой попытке, включая UPSERT-ретраи: по
  нему считается `max_posts_per_day` (`count_attempts_today`), потому что ретраи
  тоже расходуют LLM-вызовы.
- `rejected_text` — отклонённый валидатором вывод (обрезка ~2000): без него
  критерий раскатки «0 ложных срабатываний валидатора» непроверяем — не видно,
  что именно отклонено.
- `prompt_version` = sha1(prompt)[:8] считается автоматически — ручное
  обновление версии промпта забудется.

### Три класса ошибок

| Класс | Примеры | attempts | Реакция |
|---|---|---|---|
| Контентные | провал валидатора, parse_mode | +1, до `max_attempts` = 3 | рерайт в следующем цикле |
| Инфраструктурные | таймаут, сеть, HTTP 429/5xx, сбои Telegram-сети | не растут | circuit breaker: после 2–3 подряд цикл прерывается (экономия токенов), новости ретраятся в следующем цикле без штрафа |
| Конфиг/доступ | HTTP 401/402/403/404 — протух ключ, кончился баланс, неверное имя модели | не растут | немедленная авто-пауза (флаг `factory_autopause` в `sources_state`) + немедленный алерт админу; снимается `/factory resume` |

Конфиг/доступ выделен в отдельный класс, потому что ретраи здесь бессмысленны:
без этого за три цикла сбоя провайдера все новости окна ушли бы навсегда в
`failed`. Тексты ошибок в posts и событиях — без заголовков запросов и ключей,
обрезка ~300 символов.

### Recovery и at-least-once

В начале каждого цикла draft старше `stale_draft_minutes` публикуется повторно:
текст уже в БД, LLM не вызывается. Recovery уважает текущий dry_run, паузу и
тихие часы и занимает место в `posts_per_cycle` и `max_posts_per_day`.

Семантика доставки — **at-least-once**, и это осознанный компромисс: падение
процесса между успешной отправкой в Telegram и `mark_post_published` даст дубль
поста при восстановлении. Цена exactly-once (координация транзакций между
Telegram API и SQLite) для соло-проекта не оправдана, а окно между send и mark
исчезающе мало. Дубли при краше редки и убираются `/factory retract`.

### Дедупликация фабрики

Кандидат отбрасывается, если:

- есть строка posts со статусом `draft | published | previewed | skipped`;
- или `failed` с `attempts >= max_attempts` (контентные ошибки);
- или Jaccard заголовков ≥ ~0.7 против постов за 7 дней или внутри пачки
  текущего цикла (нормализованные токены заголовков, stdlib — без новых
  зависимостей).

`sent_news` фабрика не читает и не пишет: дайджест и фабрика — независимые
потребители одних RSS-источников. Раньше была однонаправленная проверка
(фабрика не брала вышедшее дайджестом), но при пустых `include_keywords`
дайджеста она оставляла фабрику без потока новостей. Дубль в канале
(ссылка в дайджесте + пост фабрики по той же новости) принят осознанно:
пост — переработка, а не повтор ссылки; дайджест — «быстрая полоса», его
код не трогаем.

`failed` с запасом попыток рерайтится в следующем цикле: UPSERT по каноническому
`news_url`, attempts растёт только за контентное.

### Политика «ссылку на источник добавляет код»

Промпт запрещает LLM выводить любые ссылки; валидатор отклоняет вывод, содержащий
URL или `<a href>`; ссылку на источник (`news_url`) код добавляет к сообщению при
отправке. Почему так:

- инъекция через ссылку невозможна: LLM не контролирует ни один URL в итоговом
  сообщении, проверка доменов не нужна;
- редиректы и агрегаторы не ломают валидацию: ссылка ведёт на исходный URL как
  есть, каким бы «некрасивым» он ни был.

Защита от prompt injection в тексте: данные новости оборачиваются в разделители
`<article>…</article>`; system-prompt явно требует использовать только факты из
статьи и не выполнять инструкции из её текста.

Пометка «подготовлено с помощью ИИ» решением владельца не добавляется (юрисдикция
РФ, требования ЕС неприменимы). Если понадобится — одна опция конфига в месте,
где код добавляет ссылку на источник.

### Раздельные локи, общие ресурсы

У дайджеста и фабрики — разные `asyncio.Lock`: циклы независимы и не должны
блокировать друг друга. Но ресурсы у них общие:

- **Telegram-лимиты**: оба цикла публикуют в один канал одним ботом.
  `PostPublisher` обрабатывает `TelegramRetryAfter` (спать `retry_after`,
  повторить, до 2–3 раз) и выдерживает паузу ~2–3 с между постами.
- **Одна SQLite**: включён WAL, `busy_timeout` выставляется на каждом соединении
  (`timeout=` в `sqlite3.connect`); каталог `data/` монтируется в Docker целиком,
  а не отдельным файлом — WAL-файлы живут на volume (проверено по
  `infra/compose.prod.yml` и VPS-варианту `data:/app/data`).

Короткие транзакции плюс WAL делают одновременную запись двух циклов безопасной.

### Управление

Единое правило включённости:

```
enabled = (env FACTORY_ENABLED, если задан, иначе yaml factory.enabled)
          AND не paused (ручная пауза, /factory pause)
          AND не auto-paused (сбой конфига/доступа; снимается /factory resume)
```

- `factory.dry_run`: пост генерируется и отправляется админам в личку вместо
  канала; статус `previewed` терминальный — после выключения dry-run пост
  автоматически в канал не уйдёт. Для healthcheck и алертов `previewed`
  считается успехом.
- `/factory pause | resume`: флаг в БД (`sources_state`, name='factory') —
  остановка цикла без редеплоя; `resume` снимает и ручную, и авто-паузу.
- `/factory run` — ручной запуск цикла; `/factory status` — состояние и причина
  остановки (paused / autopause с кодом ошибки).
- `/factory retract <id>` — удаляет сообщение из канала по `message_id`
  (`bot.delete_message`), только админ. Страховочный механизм вместо постоянной
  модерации.
- `/posts` — последние посты со статусами, попытками и обрезанными ошибками.
- Все команды фабрики админские (`ADMIN_IDS`).
- `enabled=true` без `LLM_API_KEY` — ошибка старта (ValueError): секреты живут
  только в `.env`.

### Тихие часы и heartbeat

`factory.active_hours` («08:00–23:00») в таймзоне из `factory.timezone` (zoneinfo,
stdlib). Вне окна и на паузе цикл пишет heartbeat-событие `factory_run` с JSON
`{"state": "idle", "reason": "quiet_hours" | "paused"}` — healthcheck не краснеет
ночью и на паузе.

### Наблюдаемость и healthcheck

- `factory_run` (рабочие циклы) пишет в `details` JSON-счётчики стадий
  `collected/filtered/deduped/written/skipped/published|previewed/failed`,
  латентность LLM и токены. В отличие от текстовых деталей дайджеста, JSON
  машиночитаем: по нему работают healthcheck, счётчик неудачных циклов и дедуп
  алертов.
- «Неудачный цикл» = `written == 0 and failed > 0`. Цикл, где всё получило SKIP, —
  не авария. После `alert_after_failed_cycles` (3) подряд — **одно** сообщение
  админам на инцидент (факт отправки фиксируется событием `factory_alert`, без
  спама каждый цикл) и одно сообщение при восстановлении.
- Конфиг/доступ — немедленный алерт и авто-пауза, вне счётчика N циклов.
- Healthcheck фабрики: «нет публикаций (или previewed в dry-run) дольше X часов
  при наличии кандидатов» → unhealthy; heartbeat — признак живого цикла. Правило
  «нет публикаций» проверяется **только внутри активного окна**, а X вычисляется
  как длина окна + один интервал цикла (не задаётся вручную) — иначе ночное окно
  (9 ч в примере) покраснело бы к 07:00 при последнем посте в 22:30, хотя
  heartbeat подтверждает живой цикл.

### Глобальный обработчик ошибок бота

Хендлеры команд не оборачиваются в try/except по одному: исключение из любого
хендлера ловится единым обработчиком `dp.errors` (`bot/error_handler.py`):

- лог `unhandled_error` с полным traceback — единственное место, где traceback
  попадает в лог;
- событие `error` в `bot_stats` (детали обрезаны до 300 символов — секреты
  не утекают), отображается в `/status`;
- короткий ответ пользователю («Internal error occurred…»);
- `return True` — ошибка считается обработанной, aiogram не рерайзит.

Сам обработчик не поднимает исключений: запись в БД и ответ пользователю
обёрнуты в try/except (если БД или Telegram недоступны — только лог).
Scheduler-циклы (`bot/scheduler.py`) обрабатывают свои ошибки самостоятельно
и через `dp.errors` не проходят.

### Миграции

Миграции — `PRAGMA user_version`, список шагов в одном месте (`utils/db.py`):

- v1 — существующие таблицы (`sent_news`, `bot_stats`, `sources_state`)
  идемпотентно: прод-БД со старой версией `user_version = 0` корректно
  поднимается до актуальной;
- v2 — таблица `posts` с полным набором колонок (см. «Машина состояний posts»);
- перед применением v2 — копия файла БД (откат = вернуть копию).

WAL включается на инициализации, `busy_timeout` — на каждом соединении.

---

## Конфигурация

`sources.yaml` хранит только несекретные настройки:

```yaml
settings:
  post_interval_hours: 6
  max_news_per_source: 5
  request_timeout: 30

filters:
  include_keywords: []
  exclude_keywords: []

sources:
  - name: "Python Insider"
    type: "rss"
    url: "https://pythoninsider.blogspot.com/feeds/posts/default"
    enabled: true
    category: "python"
```

`.env` хранит секреты и runtime-переопределения:

```env
BOT_TOKEN=
CHANNEL_ID=
ADMIN_IDS=
LOG_LEVEL=INFO
POST_INTERVAL_HOURS=6
REQUEST_TIMEOUT=30
```

Переменные окружения имеют приоритет над YAML, чтобы настройки можно было менять в Docker без пересборки образа.

У фабрики — своя секция `factory:` в том же YAML и переменные `FACTORY_ENABLED`,
`FACTORY_INTERVAL_HOURS`, `LLM_BASE_URL`, `LLM_MODEL` (переопределяют yaml, если
заданы); `LLM_API_KEY` — только в `.env`. Полный список ключей — в
`news_bot/README.md`, раздел «Конфигурация фабрики».

---

## SQLite

SQLite достаточно для небольшого production-бота. База лежит в `data/news_bot.db`, папка `data/` монтируется как Docker volume.

```sql
CREATE TABLE sent_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bot_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sources_state (
    name TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Отдельная миграционная система не нужна: создание и изменения схемы живут в `utils/db.py` в одном месте, версия схемы — `PRAGMA user_version` (v1 — таблицы дайджеста идемпотентно, v2 — таблица `posts` фабрики, с копией БД перед применением; см. «Миграции» в разделе «Контент-фабрика»). Флаги управления фабрикой (`factory`, `factory_autopause`) переиспользуют `sources_state`.

---

## Логирование

Нужно два уровня наблюдаемости:

- обычные application logs в stdout для Docker;
- бизнес-события в `bot_stats`: запуск, успешная публикация, ошибка источника, ошибка Telegram.

Минимальный формат логов:

```text
2026-05-25 12:00:00 INFO news_bot.pipeline collected=12 published=5 skipped=7
2026-05-25 12:00:02 ERROR news_bot.parsers.rss source=Example error="timeout"
```

На старте достаточно `logging.basicConfig`. Ротацию файлов можно добавить позже, если бот запускается не только в Docker.

---

## Docker

Минимальный Docker setup:

- `python:3.12-slim`;
- непривилегированный пользователь;
- `restart: unless-stopped`;
- `env_file: .env`;
- volume `./data:/app/data`;
- healthcheck, который проверяет, что процесс жив и недавно выполнял цикл.

```yaml
services:
  newsbot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
```

---

## Тесты

Минимальный набор тестов:

- `test_loader.py` — YAML читается, env-переменные переопределяют настройки;
- `test_filters.py` — include/exclude ключевые слова работают ожидаемо;
- `test_pipeline.py` — новая новость публикуется, дубликат пропускается;
- `test_formatter.py` — Telegram-сообщение не превышает лимит;
- `test_db.py`, `test_text.py` — миграции, UPSERT/`last_attempt_at`, флаги, канонизация URL, Jaccard;
- `test_factory.py` — recovery, attempts только за контентное, circuit breaker, автопауза на 401/404, лимиты, дедуп, тихие часы;
- `test_llm_writer.py` — `LlmWriter` против локального aiohttp-тест-сервера (`/chat/completions`: 200/401/404/429/500, таймаут, мусорный JSON);
- `test_validator.py`, `test_sanitize.py` — границы длин, отказ-фразы, «злые» кейсы санитайзера.

Интеграционные тесты с Telegram API на MVP не нужны. Telegram лучше мокать через `Publisher`.

Сетевой тест RSS и тест с реальным LLM помечены `@pytest.mark.network` и `@pytest.mark.llm` и исключены из дефолтного прогона (`addopts = -m "not network and not llm"`); `uv run pytest -m llm` — ручная регрессия промпта с реальным ключом.

---

## Зависимости MVP

```text
aiogram==3.*
aiohttp
feedparser
pyyaml
python-dotenv
pytest
pytest-asyncio
```

Зависимости задаются в `pyproject.toml` (корень репозитория), локально — `uv sync`.

HTML-зависимости добавляются позже:

```text
beautifulsoup4
lxml
```

---

## Итоговое решение

Проект развивается от маленького production-бота, а не от большой платформы.

В MVP реализуются только RSS, дедупликация, Telegram-публикация, Docker, логи, lock и базовые команды. Для будущей фабрики контента заранее вводятся только две легкие границы: `NewsItem` и `Publisher`.

Контент-фабрика добавлена позже вторым параллельным циклом, не сломав этих границ: `Publisher` остался контрактом дайджеста, а фабрика получила свои протоколы (`Writer`, `PostPublisherProtocol`, `Alerter`) — см. «Контент-фабрика».

Такой подход сохраняет проект простым сейчас и не мешает встроить его в более крупную систему позже.
