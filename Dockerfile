FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY news_bot ./news_bot/

ENV PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

RUN chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "news_bot.main"]
