#!/bin/sh
set -eu

.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn fretflow.api:app --host 0.0.0.0 --port "${PORT:-8000}"
