#!/bin/sh
set -eu

if [ "${1:-}" = "preflight" ]; then
  shift
  exec python -m fretflow.gpu_preflight "$@"
fi

python -m fretflow.gpu_preflight \
  --require-gpu \
  --model-dir "${FRETFLOW_MODEL_DIR:-/opt/fretflow/models/mvsep_mega}"
exec python -m fretflow.worker "$@"
