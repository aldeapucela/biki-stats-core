FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

ARG PORT=8004
ARG APP_GIT_SHA=unknown
ARG APP_VERSION=unknown
ARG APP_UID=1000
ARG APP_GID=1000
LABEL org.opencontainers.image.title="biki-stats-core" \
      org.opencontainers.image.revision="$APP_GIT_SHA" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.source="https://github.com/aldeapucela/biki-stats-core"

WORKDIR /app
ENV APP_PORT=${PORT}
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini

RUN pip install --no-cache-dir .

EXPOSE ${PORT}
CMD ["sh", "-c", "exec uvicorn movilidad.api.main:app --host 0.0.0.0 --port \"$APP_PORT\""]
