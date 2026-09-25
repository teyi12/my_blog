# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 1001 --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 10000

CMD ["sh", "-c", "python manage.py collectstatic --noinput && exec gunicorn blog.wsgi:application --bind 0.0.0.0:${PORT} --timeout 60 --graceful-timeout 30"]
