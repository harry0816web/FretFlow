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
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="FretFlow API" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.created="$BUILD_DATE" \
      org.opencontainers.image.source="https://github.com/harryp/FretFlow"
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

FROM nvidia/cuda:13.0.2-cudnn-runtime-ubuntu22.04@sha256:78badc969903e2aebc515b087f6276a15eae17c6aade19068b18dc252bd6ec90 AS gpu-python-base
ARG TORCH_VERSION=2.11.0+cu130
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates curl ffmpeg python3.10 python3.10-dev python3.10-distutils python3.10-venv \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/0.11.14/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project \
    && uv pip install --python /app/.venv/bin/python \
        --index-url "$TORCH_INDEX_URL" "torch==$TORCH_VERSION"
COPY requirements-mvsep.txt ./
RUN uv pip install --python /app/.venv/bin/python -r requirements-mvsep.txt

FROM gpu-python-base AS gpu-worker-runtime
ENV INFERENCE_MODE=real \
    FRETFLOW_MODEL_DIR=/opt/fretflow/models/mvsep_mega \
    FRETFLOW_MVSEP_SCRIPT=/app/infer_mvsep_mega.py \
    FRETFLOW_SKIP_MODEL_CHECKSUM=true
COPY fretflow/ ./fretflow/
COPY basic_pitch_tab.py download_mvsep_mega.py infer_mvsep_mega.py validate_gpu_smoke.py ./
COPY docker/gpu-entrypoint.sh ./docker/gpu-entrypoint.sh
RUN mkdir -p /opt/fretflow/models/mvsep_mega /var/lib/fretflow/artifacts /var/lib/fretflow/work \
    && chmod +x ./docker/gpu-entrypoint.sh \
    && useradd --create-home --uid 10001 fretflow \
    && chown -R fretflow:fretflow /app /opt/fretflow /var/lib/fretflow

FROM gpu-worker-runtime AS gpu-worker
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="FretFlow GPU Worker" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.created="$BUILD_DATE" \
      org.opencontainers.image.source="https://github.com/harryp/FretFlow"
COPY THIRD_PARTY_NOTICES.md ./
COPY licenses/ ./licenses/
RUN --mount=type=cache,target=/root/.cache/fretflow-model \
    python download_mvsep_mega.py --output-dir /root/.cache/fretflow-model \
    && cp /root/.cache/fretflow-model/* /opt/fretflow/models/mvsep_mega/ \
    && python -m fretflow.gpu_preflight \
        --model-dir /opt/fretflow/models/mvsep_mega
USER fretflow
ENTRYPOINT ["./docker/gpu-entrypoint.sh"]
