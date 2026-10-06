# Управление и мониторинг базы данных

БД проекта — SQLite в режиме WAL: `news_bot/data/news_bot.db` (в git не попадает,
в проде путь задаётся `DATABASE_PATH`, см. `infra/compose.prod.vps.yml`).

Рядом с ней лежат служебные файлы:

| Файл | Что это |
|---|---|
| `news_bot.db-wal`, `news_bot.db-shm` | журнал и индекс WAL; не удалять при работающем боте |
| `news_bot.db.bak-vN` | автокопия перед миграцией схемы (создаётся при старте бота) |

## Схема

Версия схемы — `PRAGMA user_version` (сейчас 2). Миграции применяются
автоматически при старте (`news_bot/utils/db.py`), вручную ничего запускать не нужно.

| Таблица | Назначение |
|---|---|
| `sent_news` | дедупликация дайджеста: новости, уже отправленные дайджестом в канал (URL уникален); фабрика её не читает и не пишет |
| `bot_stats` | журнал событий: `run`, `error`, `publish`, `factory_run`, `factory_pause`/`resume`, `factory_retract`, `factory_alert` |
| `sources_state` | флаги состояния: `factory` (ручная пауза), `factory_autopause` |
| `posts` | посты контент-фабрики: `status` (`draft`/`previewed`/`published`/`failed`/`skipped`), `attempts`, `error`, `tokens` и т.д. |

## Мониторинг

**Команды бота** (в Telegram; `/posts` и `/factory` — только для админов из `ADMIN_IDS`):

- `/status` — uptime, время последнего цикла и последней ошибки;
- `/stats` — публикации и ошибки по дням (7 дней);
- `/posts` — последние 10 постов фабрики со статусами и ошибками;
- `/factory status` — состояние фабрики: пауза, auto-pause, последний цикл.

**Healthcheck (Docker)** — `news_bot/scripts/healthcheck.py`: падает, если нет
свежих событий `run` (дайджест) или `factory_run` (фабрика), либо если в активном
окне долго нет публикаций. `docker inspect --format '{{.State.Health}}' <container>`.

**Запросы руками** (sqlite3 CLI нет, используем Python; из корня репозитория):

```bash
uv run python - <<'PY'
import sqlite3
conn = sqlite3.connect("file:news_bot/data/news_bot.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

print(conn.execute("PRAGMA user_version").fetchone()[0])          # версия схемы
for t in ("sent_news", "bot_stats", "sources_state", "posts"):    # размеры
    print(t, conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])

for r in conn.execute(  # последние события фабрики
    "SELECT created_at, event, substr(details,1,100) d "
    "FROM bot_stats ORDER BY id DESC LIMIT 15"):
    print(r["created_at"], r["event"], r["d"])

for r in conn.execute(  # посты по статусам + ошибки
    "SELECT status, COUNT(*) n FROM posts GROUP BY status"):
    print(dict(r))
PY
```

На VPS то же самое — внутри контейнера:
`docker compose -f infra/compose.prod.vps.yml exec bot python - <<'PY' ...`
(путь к БД там `/app/data/news_bot.db`).

## Управление

- **Пауза/возобновление фабрики** — `/factory pause`, `/factory resume`
  (пишется в `sources_state` + событие в `bot_stats`).
- **Отзыв поста из канала** — `/factory retract <post_id>` (id виден в `/posts`).
- **Ручной запуск цикла** — `/factory run`.

**Бэкап** (безопасен при работающем боте, WAL подхватится):

```bash
uv run python -c "import sqlite3; sqlite3.connect('news_bot/data/news_bot.db').execute(\"VACUUM INTO 'news_bot/data/backup.db'\")"
```

**Чистка старых данных** (MVP не чистит сам; перед удалением — бэкап):

```sql
DELETE FROM bot_stats WHERE created_at < datetime('now', '-30 days');
```

## Чего не делать

- Не удалять `*.db-wal` / `*.db-shm` при работающем боте и не копировать
  основную БД без WAL-файла — данные в WAL могут ещё не быть в основном файле.
- Не редактировать `posts`/`sent_news` руками без бэкапа: ручной `DELETE`
  из `posts`/`sent_news` ломает дедупликацию и может привести к повторной публикации.
- Не коммитить БД и бэкапы — `news_bot/data/` в `.gitignore`.
