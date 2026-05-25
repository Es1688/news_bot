# Architecture — Content Fabric News Bot

Небольшой production-бот для сбора новостей из RSS-источников и публикации в Telegram-канал.
Проект должен оставаться простым: сначала автономный Telegram-бот, затем аккуратное встраивание в систему фабрики контента.

Главный принцип: отделить сбор и подготовку новости от способа публикации. Сегодня выходом является Telegram, позже тем же ядром сможет пользоваться фабрика контента.

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

### 4. Интеграция с фабрикой контента

Когда Telegram-бот стабилен, добавляется второй способ публикации:

- `TelegramPublisher` продолжает отправлять новости в канал;
- `ContentFactoryPublisher` передает `NewsItem` во внутренний API, webhook или очередь фабрики;
- ядро сбора новостей не меняется.

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
      |
      +--> ContentFactoryPublisher (позже)
```

Ключевая идея: `Publisher` является границей между ядром бота и внешней системой публикации.

---

## Структура проекта

```
news_bot/
├── bot/
│   ├── handlers.py          # команды Telegram
│   └── scheduler.py         # периодический запуск pipeline
│
├── config/
│   ├── loader.py            # YAML + .env
│   ├── sources.yaml         # RSS-источники и настройки
│   └── __init__.py
│
├── core/
│   ├── models.py            # NewsItem, PublishedResult
│   ├── pipeline.py          # fetch -> filter -> dedupe -> publish
│   └── __init__.py
│
├── parsers/
│   ├── base.py              # интерфейс fetcher
│   ├── rss.py               # RSS/Atom fetcher
│   └── __init__.py
│
├── publishers/
│   ├── base.py              # интерфейс Publisher
│   ├── telegram.py          # публикация в Telegram
│   └── __init__.py
│
├── utils/
│   ├── db.py                # SQLite, дедупликация, статистика
│   ├── filters.py           # keyword-фильтрация
│   ├── formatter.py         # Telegram-текст
│   └── logging.py           # настройка логирования
│
├── data/
│   └── news_bot.db          # Docker volume
│
├── tests/
│   ├── test_filters.py
│   ├── test_loader.py
│   └── test_pipeline.py
│
├── main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
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
```

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

На первом этапе реализуется только `TelegramPublisher`. В будущем добавляется `ContentFactoryPublisher`, который может отправлять те же `NewsItem` во внутреннюю систему.

Это не усложняет MVP, но защищает проект от переписывания, когда бот станет частью фабрики контента.

---

## Поток одного цикла

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

Для MVP не нужна отдельная миграционная система. Достаточно держать создание и простые изменения схемы в `utils/db.py`, но в одном месте и с явной версией схемы.

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
- `test_formatter.py` — Telegram-сообщение не превышает лимит.

Интеграционные тесты с Telegram API на MVP не нужны. Telegram лучше мокать через `Publisher`.

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

HTML-зависимости добавляются позже:

```text
beautifulsoup4
lxml
```

---

## Итоговое решение

Проект развивается от маленького production-бота, а не от большой платформы.

В MVP реализуются только RSS, дедупликация, Telegram-публикация, Docker, логи, lock и базовые команды. Для будущей фабрики контента заранее вводятся только две легкие границы: `NewsItem` и `Publisher`.

Такой подход сохраняет проект простым сейчас и не мешает встроить его в более крупную систему позже.
