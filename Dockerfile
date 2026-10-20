FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="biki-stats-core" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.source="https://github.com/aldeapucela/biki-stats-core"

WORKDIR /app
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "movilidad.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
