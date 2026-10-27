# syntax=docker/dockerfile:1.7

FROM node:22.20.0-bookworm-slim AS web-build
WORKDIR /build/sites/fretline
COPY sites/fretline/package.json sites/fretline/package-lock.json ./
RUN npm ci
COPY sites/fretline/ ./
RUN npm run build

FROM python:3.10.19-slim-bookworm AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.14
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python-base AS app
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY fretflow/ ./fretflow/
COPY basic_pitch_tab.py ./
COPY docker/entrypoint.sh ./docker/entrypoint.sh
COPY --from=web-build /build/sites/fretline/dist ./static/
RUN mkdir -p /var/lib/fretflow/artifacts \
    && chmod +x ./docker/entrypoint.sh \
    && useradd --create-home --uid 10001 fretflow \
    && chown -R fretflow:fretflow /app /var/lib/fretflow
USER fretflow
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD curl --fail http://127.0.0.1:8000/api/health || exit 1
ENTRYPOINT ["./docker/entrypoint.sh"]

FROM app AS dev
USER root
COPY *.py ./
COPY tests/ ./tests/
RUN uv sync --frozen --group dev --no-install-project \
    && chown -R fretflow:fretflow /app
USER fretflow
