FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./news_bot/

ENV PYTHONPATH=/app

RUN chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "news_bot.main"]
