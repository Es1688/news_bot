# Task: content-factory

- Дата: 2026-10-02 (ревизии: 2026-10-05 №1 — внешнее ревью, P0/P1 включены;
  №2 — устранены противоречия, закрыты прод-дыры, числовые критерии раскатки;
  №3 — снят вопрос ai_disclaimer: владелец решил пометку не добавлять;
  №4 — класс ошибок «конфиг/доступ» с авто-паузой, окно для healthcheck,
  rejected_text для измеримости раскатки)
- Проект: content-fabric
- Ветка: feature/content-fabric (создаёт агент A1, волна 1)
- Статус: done (код, 2026-10-06: волны 1–4 команды агентов + adversarial review
  + live-верификация и фикс reasoning; раскатка — шаг 5 плана — у владельца,
  dry-run идёт; было: запущена команда агентов по волнам)

## Задача

Превратить бота из «дайджеста ссылок» в контент-фабрику: второй независимый
цикл «поиск информации → написание поста (LLM) → автопубликация в
Telegram-канал», работающий параллельно с существующим дайджест-пайплайном в
том же процессе и том же канале. Автопубликация включается только после
раскатки через dry-run с числовыми критериями выхода.

## Требования

### Базовые решения (подтверждены пользователем 2026-10-02)

- Написание: LLM переписывает найденные по ключевым словам новости в
  оригинальные посты (ссылку на источник добавляет код, не LLM — см. P0.2).
- Провайдер: OpenAI-совместимый API (`base_url` + `model` в конфиге; совместим
  с OpenAI, OpenRouter, vLLM/Ollama). Клиент на уже имеющемся aiohttp — новых
  pip-зависимостей нет.
- Публикация: автопубликация после генерации (без постоянной модерации);
  безопасный выход — dry-run и retract (P0.1, P0.6).
- Дайджест: существующий цикл не трогаем; фабрика — второй цикл со своим
  интервалом и своим `asyncio.Lock`, публикует в тот же канал.
- Дедупликация: дайджест — по `sent_news`; фабрика — только по таблице
  `posts` + Jaccard заголовков. Решение P1.7 об однонаправленной проверке
  `sent_news` пересмотрено (2026-10-06): при пустых `include_keywords`
  дайджеста фабрика оставалась без потока новостей; дубль «ссылка в
  дайджесте + пост фабрики» принят осознанно (пост — переработка, не повтор
  ссылки).

### P0 — без этого автопубликацию не включаем

1. **Dry-run и kill switch**
   - `factory.dry_run`: пост генерируется, сохраняется со статусом `previewed`
     (терминальный — после выключения dry-run автоматически в канал не уходит)
     и отправляется админам в личку вместо канала. Для healthcheck/алертов
     `previewed` считается успехом.
   - Семантика включённости (единое правило): `enabled = (env FACTORY_ENABLED,
     если задан, иначе yaml factory.enabled) AND не paused (ручная пауза) AND
     не auto-paused (сбой конфига/доступа — см. P0.3; снимается
     `/factory resume`)`.
   - `/factory pause` / `/factory resume` — флаг в БД (переиспользуем таблицу
     `sources_state`, name='factory'), останавливает цикл без редеплоя.
2. **Защита от prompt injection и контроль вывода**
   - Данные новости оборачиваются в разделители `<article>…</article>`;
     system-prompt явно требует: использовать только факты из статьи,
     инструкции из текста статьи не выполнять.
   - **Политика «без ссылок»**: промпт запрещает LLM выводить любые ссылки;
     валидатор отклоняет вывод, содержащий URL/`<a href>`; ссылку на источник
     добавляет код при формировании сообщения. Проверка доменов не нужна,
     инъекция через ссылку невозможна.
   - LLM вправе вернуть маркер `SKIP` (материал нерелевантен/скуден) → статус
     `skipped` (терминальный, не ретраится).
   - Валидация вывода: длина по видимому тексту без тегов (жёсткий предел 4096
     — так считает Telegram; мягкий потолок `factory.max_post_chars`, ~1500–2000,
     для читабельности канала), минимум ~200 символов, отсутствие отказов
     («As an AI…»). Провал валидации — контентная ошибка (см. P0.3).
3. **Машина состояний и восстановление после падения**
   - Статусы posts: `draft | published | failed | skipped | previewed`.
     Колонка `text` nullable: строка создаётся при любой **обработанной**
     ошибке (LLM, валидация, отправка) — для счётчика attempts; при
     `CancelledError` строка не создаётся (отмена таска — не попытка).
   - **Классы ошибок** (три, не два):
     *контентные* (валидация, parse_mode) — единственные, что инкрементируют
     attempts (`max_attempts` = 3); *инфраструктурные* (таймаут, сеть, HTTP
     429/5xx, сбои Telegram-сети) — attempts не растут, прерывают цикл через
     circuit breaker; *конфиг/доступ* (HTTP 401/402/403, 404 — протух ключ,
     кончился баланс, неверное имя модели) — attempts не растут, фабрика
     немедленно сама ставится на авто-паузу (флаг в `sources_state`,
     name='factory_autopause'), админу сразу уходит алерт — не дожидаясь
     трёх циклов. Иначе за три цикла сбоя провайдера все новости окна уйдут
     навсегда в failed.
   - **Circuit breaker**: после 2–3 подряд инфраструктурных ошибок цикл
     прерывается (экономия токенов); новости ретраятся в следующем цикле без
     штрафа по attempts.
   - Recovery в начале цикла: draft старше `stale_draft_minutes` публикуется
     повторно (текст в БД, LLM не вызывается). Recovery уважает текущий
     dry_run/pause/тихие часы и занимает место в `posts_per_cycle` и
     `max_posts_per_day`. Семантика at-least-once: падение между успешной
     отправкой и `mark_post_published` даст дубль — осознанно принято для
     соло-проекта.
   - **Защита от бэклога на первом запуске**: фильтр по возрасту
     `factory.max_news_age_hours` (по `NewsItem.published_at`, по умолчанию
     24ч); новости без даты в отбор фабрики не попадают (решение зафиксировано).
4. **Лимиты расходов**
   - `factory.max_posts_per_day` — считается по колонке `last_attempt_at`
     (обновляется при каждой попытке, включая UPSERT-ретраи), а не по
     `created_at`: ретраи тоже расходуют LLM-вызовы.
   - `usage` (токены) из ответа LLM пишется в posts.tokens и агрегируется в
     `factory_run`. Тексты ошибок в posts.error и событиях — без заголовков
     запросов и ключей, обрезка до ~300 символов.
5. **Устойчивость Telegram-отправки**
   - Обработка `TelegramRetryAfter` (спать `retry_after`, повторить, до 2–3
     раз), пауза ~2–3 с между постами.
   - Санитайзер: весь текст вне whitelist прогоняется через `html.escape`;
     `href` только http/https; несбалансированные whitelist-теги — немедленный
     fallback; fallback вычищает теги и экранирует текст, а не шлёт сырой вывод.
6. **Отзыв поста**
   - Колонка `posts.message_id` (для канальных отправок; в dry-run — NULL).
   - `/factory retract <id>` — удаляет сообщение из канала
     (`bot.delete_message`), только админ. Страховочный механизм вместо
     модерации.

### P1 — качество и надёжность

7. **Дедуп**: канонизация URL перед UNIQUE (срезать `utm_*`, `fbclid`,
   фрагмент, trailing slash, нижний регистр хоста); fuzzy-дедуп заголовков
   (нормализованные токены, Jaccard ≥ ~0.7) против постов за 7 дней и внутри
   пачки цикла. Проверка `sent_news` убрана (2026-10-06, пересмотр решения):
   дайджест и фабрика — независимые потребители, дубль в канале допустим.
   Без новых зависимостей.
8. **Схема БД с запасом**: `PRAGMA user_version` + список миграций в `db.py`
   (v1 — существующие таблицы идемпотентно; v2 — posts). Колонки posts:
   `attempts, error, prompt_version, llm_model, tokens, created_at,
   published_at, last_attempt_at, message_id, rejected_text` (+ news_url
   UNIQUE по каноническому URL, status, text nullable). `rejected_text` —
   отклонённый валидатором вывод (обрезанный, ~2000 символов): без него
   критерий раскатки «0 ложных срабатываний валидатора» непроверяем — не
   видно, что именно отклонено. `prompt_version` считается автоматически как
   `sha1(prompt)[:8]` (ручное обновление забудется).
   WAL + busy_timeout: перед v2 — копия файла БД; монтирование каталогом
   данных (а не одного файла) уже проверено по `infra/compose.prod.yml` и VPS
   варианту (`data:/app/data`) — WAL работать будет.
9. **Тихие часы + heartbeat**: `factory.active_hours` («08:00–23:00», TZ из
   `factory.timezone`, zoneinfo stdlib). Вне окна и на паузе цикл пишет
   heartbeat-событие `factory_run` с JSON `{"state": "idle", "reason":
   "quiet_hours" | "paused"}` — healthcheck не краснеет ночью и на паузе.
10. **Наблюдаемость**: `factory_run` (рабочие циклы) пишет JSON-счётчики стадий
    `collected/filtered/deduped/written/skipped/published|previewed/failed` +
    латентность LLM + токены. Healthcheck: «нет публикаций (или previewed в
    dry-run) дольше X часов при наличии кандидатов» → unhealthy; heartbeat —
    признак живого цикла. Правило «нет публикаций» проверяется **только внутри
    активного окна**, а X по умолчанию вычисляется как длина окна + один
    интервал цикла — иначе ночное окно (9 ч в примере) покраснело бы в 07:00
    при последнем посте в 22:30, хотя heartbeat подтверждает живой цикл.
    Алерты админам: «неудачный цикл» = `written == 0 and failed > 0` (цикл,
    где всё получило SKIP, — не авария); после `alert_after_failed_cycles` (3)
    подряд — **одно** сообщение на инцидент (факт фиксируется событием
    `factory_alert`, без спама каждый цикл) + одно сообщение при
    восстановлении; конфиг/доступ — немедленный алерт и авто-пауза (P0.3),
    вне счётчика N циклов.
11. **Тестируемость**: `ContentFactory` зависит от протоколов (`Fetcher`,
    `Writer`, `PostPublisherProtocol`). Результат `Writer` — явный
    `WriteResult(status: written | skipped | error, post | None,
    error_kind: infra | content | config, error (обрезанный), tokens,
    latency_ms)` — различает SKIP/ошибку/успех и несёт usage. `LlmWriter`
    тестируется через локальный aiohttp-тест-сервер (/chat/completions: 200,
    401, 404, 429, 500, таймаут, мусорный JSON). Тесты: recovery (падение
    между save и send), prompt injection, «злые» тесты санитайзера,
    классификация ошибок (в т.ч. конфиг/доступ → авто-пауза) и circuit
    breaker. Отдельный тест с реальным LLM — маркер `@pytest.mark.llm`
    (ручной прогон, регрессия промпта).
12. **Сетевой тест**: `test_habr_rss_feed_returns_items` →
    `@pytest.mark.network`, исключён из дефолтного прогона
    (`addopts = -m "not network and not llm"`).
13. **Жизненный цикл ресурсов**: один общий `aiohttp.ClientSession` на процесс
    (передаётся в RssFetcher и LlmWriter, закрывается при shutdown; RssFetcher
    — backwards-compatible опциональный параметр). Отмена таска посреди
    LLM-вызова не оставляет артефактов: строка posts не создаётся при
    CancelledError, «зависший» draft ловит recovery.

## Ограничения

- RSS-only для источников (AGENTS.md Level 1); HTML-парсинг — только через ADR.
- Тест-бан зависимостей (`test_architecture.py`): beautifulsoup, lxml, celery,
  kafka, psycopg, sqlalchemy — не добавлять (санитайзер/очистка/дедуп — regex
  + html.unescape + stdlib).
- `core/factory.py` — без aiogram-импортов (как у `core/pipeline.py`).
- Секреты (в т.ч. `LLM_API_KEY`) — только в `.env`, в git не попадают.
- Деплой/пуш — только с явного подтверждения пользователя (Level 0 +
  project.yaml). Документация — русский; код, идентификаторы, коммиты —
  английский.
- Валидация: `uv run pytest` из корня репозитория.

### P2 — сознательно НЕ делаем (границы соло-проекта)

UI модерации (хватит dry-run, pause/resume и retract), Prometheus/Grafana
(хватает events + алертов), HTML-парсинг полных статей (ADR), картинки,
несколько каналов, векторный дедуп, очередь задач (Celery и т.п.).

## Acceptance criteria

База:
- [ ] `NewsItem.summary`; `RssFetcher` извлекает RSS-summary, чистит HTML,
      режет ~1000 символов; общая ClientSession (P1.13). Age-фильтр не
      требует изменений: `published_at` уже есть в модели и заполняется
      парсером (aware UTC) — проверено по коду 2026-10-05.
- [ ] Миграции `user_version` (v1 идемпотентно, v2 posts) с копией файла БД
      перед v2; WAL + busy_timeout; полный набор колонок posts (включая
      `last_attempt_at`, `message_id`, `rejected_text`, nullable `text`);
      методы `is_post_written`, `save_attempt` (UPSERT, обновляет
      last_attempt_at), `mark_post_published` (+message_id),
      `mark_post_failed`, `find_stale_drafts`, `count_attempts_today` (по
      last_attempt_at), `get_recent_posts`; флаги pause и autopause в
      `sources_state`.
- [ ] `Writer`-протокол возвращает `WriteResult`; `LlmWriter`: разделители
      `<article>`, анти-инъекция, политика «без ссылок», маркер SKIP,
      классификация ошибок infra/content/config, usage/токены, таймаут.
- [ ] Валидатор: нет ссылок в выводе, длина по видимому тексту (hard 4096,
      soft `max_post_chars`), минимум ~200, отсутствие отказов.
- [ ] `PostPublisher`: санитайзер + «злые» тесты; RetryAfter и паузы;
      dry-run → админам; возвращает message_id; код добавляет ссылку на
      источник.
- [ ] `ContentFactory.run()`: recovery (уважает dry_run/pause/тихие часы,
      входит в лимиты); attempts только за контентные ошибки; circuit breaker
      по инфраструктурным; авто-пауза + немедленный алерт при конфиг/доступ
      (401/402/403/404); фильтр `max_news_age_hours`; канонизация URL +
      Jaccard; лимиты per_cycle и per_day (по
      last_attempt_at); heartbeat idle-события; JSON-счётчики; алерт один раз
      на инцидент + восстановление.
- [ ] Конфиг `factory:` (enabled, dry_run, interval_hours, posts_per_cycle,
      max_posts_per_day, max_attempts, stale_draft_minutes, max_news_age_hours,
      max_post_chars, active_hours, timezone, alert_after_failed_cycles,
      circuit_breaker_after, max_news_per_source, include/exclude_keywords,
      llm.{...}, prompt) + env `FACTORY_ENABLED`,
      `FACTORY_INTERVAL_HOURS`, `LLM_BASE_URL`, `LLM_MODEL`; включённость:
      env-если-задан-иначе-yaml, затем AND не-paused; enabled без
      `LLM_API_KEY` → ValueError.
- [ ] Команды: `/factory run|pause|resume|status`, `/factory retract <id>`
      (админ), `/posts` — последние посты со статусами; `/factory resume`
      снимает и авто-паузу, `/factory status` показывает состояние и причину
      (paused / autopause: код ошибки); убран `##### проверка деплоя`.
- [ ] Healthcheck: heartbeat/публикации/кандидаты — без ложного красного
      ночью, на паузе и в dry-run; правило «нет публикаций X часов»
      проверяется только внутри активного окна, X = длина окна + интервал
      цикла (вычисляется, не задаётся вручную).
- [ ] `.env.example`, ARCHITECTURE.md (включая общие Telegram-лимиты и общую
      SQLite при раздельных локах, политику «без ссылок», at-least-once),
      README обновлены.
- [ ] Маркеры `network` и `llm` исключены из дефолтного прогона.
- [ ] `uv run pytest` — зелёные; новых зависимостей в pyproject нет.

Специфика ревью:
- [ ] Dry-run: пост уходит админам, не в канал; статус `previewed`
      терминальный; для healthcheck/алертов — успех.
- [ ] Статус `skipped` не ретраится; «неудачный цикл» = written==0 и
      failed>0 (all-SKIP — не авария).
- [ ] Recovery: без LLM, в пределах лимитов; инфраструктурный сбой провайдера
      не сжигает attempts (тест на серию 429/5xx).
- [ ] Конфиг/доступ (401/402/403/404): attempts не растут, фабрика
      авто-ставится на паузу, алерт уходит немедленно (тест).
- [ ] Отклонённый валидатором вывод сохраняется в `rejected_text` (обрезан)
      — ложные срабатывания можно разобрать по `/posts`/БД.
- [ ] Первый запуск не вываливает бэклог (тест на age-фильтр).
- [ ] Санитайзер: вложенные/незакрытые теги, `javascript:`, `&`, `<`;
      fallback вычищает теги.
- [ ] Тест prompt injection (инструкция в summary не выполняется).
- [ ] Retract: удаление сообщения из канала по message_id (тест с моком бота).
- [ ] `prompt_version` = sha1(prompt)[:8] автоматически.
- [ ] Тексты ошибок без заголовков/ключей, обрезаны.

## Изменяемые файлы

Новые:
- `news_bot/writers/base.py` — протокол `Writer` + `WriteResult`
- `news_bot/writers/llm.py` — `LlmWriter` (инъекция-защита, SKIP, без ссылок,
  классификация ошибок, usage)
- `news_bot/writers/validator.py` — валидация вывода LLM
- `news_bot/writers/__init__.py`
- `news_bot/core/factory.py` — `ContentFactory` (машина состояний, лимиты,
  circuit breaker, recovery, heartbeat)
- `news_bot/publishers/post.py` — `PostPublisherProtocol` + `PostPublisher`
- `news_bot/utils/sanitize.py` — санитайзер Telegram-HTML
- `news_bot/utils/text.py` — canonical_url, токены заголовка, Jaccard
- `news_bot/tests/`: `test_factory.py` (recovery/attempts/лимиты/дедуп/тихие
  часы/circuit breaker/age-фильтр), `test_llm_writer.py` (aiohttp-тест-сервер
  + `test_llm_prompt_regression.py` с маркером llm), `test_sanitize.py`,
  `test_validator.py`

Изменяемые:
- `news_bot/core/models.py` — `NewsItem.summary`, модель `Post` (полная);
  `published_at` в NewsItem уже существует и заполняется — не трогаем
- `news_bot/parsers/rss.py` — summary + очистка; опциональная общая сессия
- `news_bot/utils/db.py` — миграции user_version (с бэкапом), WAL/busy_timeout,
  posts, методы
- `news_bot/config/loader.py`, `news_bot/config/sources.yaml` — секция factory
- `news_bot/.env.example`; `pyproject.toml` (маркеры network/llm + addopts)
- `news_bot/bot/scheduler.py` — `factory_scheduler_loop` (тихие часы,
  heartbeat)
- `news_bot/bot/handlers.py` — `/factory run|pause|resume|status|retract`,
  `/posts`
- `news_bot/main.py` — сборка фабрики, общая ClientSession, второй таск
- `news_bot/scripts/healthcheck.py`
- Существующие тесты: conftest.py, mocks.py (`MockWriter`, `MockPostPublisher`),
  test_rss.py (маркер network), test_loader.py, test_handlers.py (+retract),
  test_architecture.py (фабрика без aiogram)
- `ARCHITECTURE.md`, `README.md`, `news_bot/README.md`

## План реализации (утверждён; ревизия 2026-10-05 №2)

1. **Фундамент**: модели, миграции БД (user_version, бэкап перед v2, WAL,
   posts с полными колонками, включая last_attempt_at/message_id), summary в
   RSS-парсере, общая ClientSession, канонизация URL — с тестами.
2. **Написание и отправка (безопасные по построению)**: `Writer`→`WriteResult`,
   `LlmWriter` (разделители, анти-инъекция, без ссылок, SKIP, классификация
   ошибок), валидатор, санитайзер + `PostPublisher` (RetryAfter, паузы,
   fallback, dry-run админам, message_id, ссылку добавляет код) — с тестами,
   включая злые и инъекционные.
3. **Цикл фабрики**: `ContentFactory` — recovery, attempts только за
   контентное, circuit breaker, age-фильтр, Jaccard, лимиты (per
   day по last_attempt_at), тихие часы + heartbeat, JSON-счётчики, алерты без
   спама; kill switch + retract, конфиг, шедулер, хендлеры, main.py.
4. **Обвязка**: healthcheck (heartbeat/dry-run/candidates), `.env.example`,
   ARCHITECTURE.md, README, маркеры network/llm. **Можно делать параллельно с
   dry-run, не дожидаясь его завершения** (dry-run стартует после шага 3).
5. **Раскатка (обязательная, с числовыми критериями выхода)**:
   - Dry-run: не менее **20 постов**; владелец оценил бы **≥90%** как
     «опубликовал бы» (оценка вручную, итог фиксируется в разделе «Итог»
     этого файла — кода не требует); **0** ложных срабатываний валидатора
     (проверяемо по `rejected_text` отклонённых постов); **0** полностью
     неудачных циклов (written==0 и failed>0).
   - Тестовый канал (CHANNEL_ID на тестовый канал в .env): 2–3 дня, те же
     критерии + retract проверен вручную.
   - Прод: `posts_per_cycle: 1`, неделя без инцидентов → постепенное
     увеличение. Каждый переход — только при выполнении критериев.

## Замечания к архитектуре

- Вместо эскизного `ContentFactoryPublisher` из ARCHITECTURE.md («Путь
  развития», стадия 4) — прямой параллельный цикл `ContentFactory`,
  переиспользующий `Fetcher` и общий сбор новостей. Отразить в ARCHITECTURE.md.
- Раздельные локи у двух циклов — намеренно, но Telegram-лимиты и SQLite у
  них общие: записать в ARCHITECTURE.md (WAL/busy_timeout, паузы между
  отправками, RetryAfter).
- Семантика дедупа фабрики: кандидат отбрасывается, если есть строка posts со
  статусом `draft | published | previewed | skipped`, или `failed` с
  `attempts >= max_attempts` (контентные); `failed` с запасом попыток —
  рерайт в следующем цикле (UPSERT по каноническому news_url, attempts
  растёт только за контентное). `sent_news` фабрика не читает и не пишет.
- Ссылка на источник добавляется кодом: инъекция через ссылку невозможна,
  проверка доменов не нужна (редиректы/агрегаторы не ломают валидацию).
- At-least-once для recovery задокументирован как принятое компромиссное
  решение (соло-проект, дубли при краше между send и mark редки).
- `factory_run` пишет details в JSON (в отличие от текстовых деталей
  дайджеста) — по нему работают healthcheck, счётчик неудачных циклов и
  дедуп алертов.
- Решение владельца (2026-10-05): пометка «подготовлено с помощью ИИ» не
  добавляется (юрисдикция — РФ, ЕС-требования неприменимы). Если понадобится
  позже — одна опция конфига в месте, где код добавляет ссылку на источник.
- При старте реализации: ветка `feature/content-factory` (git-start-task),
  статус задачи in-progress; перед началом — базовый прогон `uv run pytest`
  (после перевода хабр-теста в network-маркер).

## Итог

Реализовано волнами 1–4 (2026-10-05, команда агентов по
`20261002-content-factory-team.md`): фундамент (модели, миграции user_version
с бэкапом, WAL, RSS-summary, общая ClientSession), пишущий контур
(`LlmWriter` + валидатор + санитайзер + `PostPublisher`), цикл `ContentFactory`
(recovery, классы ошибок, circuit breaker, авто-пауза, тихие часы, лимиты,
алерты), интеграция (конфиг, шедулер, хендлеры `/factory` `/posts`,
healthcheck, main.py). Внешнее adversarial-ревью — коммиты f55ac09, 815a632.
Дедуп `sent_news` убран из фабрики (пересмотр решения 2026-10-06): при пустых
`include_keywords` дайджеста фабрика оставалась без потока новостей.

Live-верификация 2026-10-06 (запуск в dry-run, OpenRouter + qwen3.8-flash)
выявила два блокера, исправлены:
1. Думающая модель расходовала весь `max_tokens` на reasoning и возвращала
   `content=null` (подтверждено живыми вызовами: 800 и даже 4000 токенов —
   весь в reasoning). Фикс: флаг `llm.disable_reasoning` → параметр OpenRouter
   `reasoning.enabled=false`; проверено — пост генерируется.
2. Промпт просил «1500–2000 символов» при `max_post_chars: 1800` — модель
   стабильно преступала лимит (2076–2245) и отбраковывалась валидатором.
   Фикс: жёсткий лимит в промпте (1500, оптимум 900–1300), выровнен во всех
   трёх копиях промпта; live-прогоны 702–1597 символов, валидатор зелёный.

Тесты: 239 passed, 1 skipped, 1 deselected (network/llm-маркеры исключены
по умолчанию). Acceptance criteria кодовой части выполнены.

Известные долги:
- Раскатка (шаг 5): dry-run ≥20 постов, оценка владельца ≥90%, 0 ложных
  срабатываний валидатора, затем тестовый канал и прод.
- Опциональный фикс не внесён: классификация `content=null` +
  `finish_reason=length` как отдельной ошибки (сейчас — криптичное «NoneType»
  с классом infra; при детерминированном сбое URL ретраится без штрафа
  attempts).
- Локальный venv переносился с другого пути: shebang'и в `.venv/bin` битые,
  `uv run pytest` падает «Failed to spawn» — лечится `uv sync`; прогон через
  `uv run --group dev python -m pytest`.
- Работающий бот подхватит конфиг только после рестарта (сделал владелец).
