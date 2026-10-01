"""Docker healthcheck: fail if the bot has not logged a run within 2x post interval."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path


def main() -> None:
    db_path = Path(os.getenv("DATABASE_PATH", "data/news_bot.db"))
    if not db_path.exists():
        sys.exit(0)

    interval_hours = int(os.getenv("POST_INTERVAL_HOURS", "6"))
    allowed_seconds = interval_hours * 7200

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT strftime('%s', MAX(created_at)) FROM bot_stats WHERE event='run'"
        ).fetchone()

    if not row or not row[0]:
        sys.exit(0)

    if time.time() - int(row[0]) < allowed_seconds:
        sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    main()
