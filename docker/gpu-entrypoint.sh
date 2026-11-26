#!/bin/sh
# Entrypoint for the gpu-worker (CUDA) and cpu-worker images.
#   preflight [args]  run the runtime check only
#   (no args)         preflight, then serve the job queue
#   <worker args>     preflight, then `python -m fretflow.worker <args>`
set -eu

backend="${FRETFLOW_WORKER_BACKEND:-cuda}"

if [ "${1:-}" = "preflight" ]; then
  shift
  exec python -m fretflow.gpu_preflight --backend "$backend" "$@"
fi

if [ "$backend" = "cuda" ]; then
  python -m fretflow.gpu_preflight \
    --backend cuda \
    --require-gpu \
    --model-dir "${FRETFLOW_MODEL_DIR:-/opt/fretflow/models/mvsep_mega}"
else
  python -m fretflow.gpu_preflight \
    --backend "$backend" \
    --model-dir "${FRETFLOW_MODEL_DIR:-/opt/fretflow/models/mvsep_mega}"
fi

if [ "$#" -eq 0 ]; then
  set -- serve
fi
exec python -m fretflow.worker "$@"
