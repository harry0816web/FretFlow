#!/usr/bin/env bash
# FretFlow local launcher: detects this machine's accelerator and starts the
# matching stack. The web app and database always run in Docker; only the
# inference worker changes:
#
#   nvidia   NVIDIA GPU   -> gpu-worker container with --gpus (CUDA)
#   mac      Apple Silicon -> native macOS worker (MPS); Docker cannot reach Metal
#   cpu      anything else -> cpu-worker container (slow, but works anywhere)
#   fixture  no models     -> fake inference inside the API, for UI development
#
# Usage: ./fretflow.sh <detect|setup-mac|up|down|status|logs> [mode]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

STATE_DIR="$ROOT/var"
MODE_FILE="$STATE_DIR/mode"
MAC_PID_FILE="$STATE_DIR/worker-mac.pid"
MAC_LOG_FILE="$STATE_DIR/worker-mac.log"
MAC_ARTIFACTS="$STATE_DIR/artifacts"
MVSEP_VENV="$ROOT/.venv-mvsep"
MODEL_DIR="${FRETFLOW_MODEL_DIR:-$ROOT/models/mvsep_mega}"
CHECKPOINT="mvsep_mega_model_bs_roformer_53_stems_v1.ckpt"

log() { printf '[fretflow] %s\n' "$*"; }
die() { printf '[fretflow] error: %s\n' "$*" >&2; exit 1; }

ensure_env() {
  # Never ship a database password in the repo: generate one per machine.
  [[ -f "$ROOT/.env" ]] && return
  local password
  password="$(openssl rand -hex 24)"
  sed "s/change-me-for-local-development/$password/g" "$ROOT/.env.example" >"$ROOT/.env"
  chmod 600 "$ROOT/.env"
  log "Created .env with a random POSTGRES_PASSWORD"
  if docker volume inspect fretflow_postgres-data >/dev/null 2>&1; then
    log "warning: an existing database volume keeps its old password; update it with:"
    log "  docker compose exec db psql -U \${POSTGRES_USER:-fretflow} -c \"ALTER USER ... PASSWORD '...'\""
  fi
}

load_env() {
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT/.env"
    set +a
  fi
}

# --- detection -------------------------------------------------------------

is_apple_silicon() {
  [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]
}

has_nvidia_gpu() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1
}

docker_has_nvidia_runtime() {
  # Docker Desktop on WSL2 exposes GPUs without listing an nvidia runtime.
  docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia \
    || grep -qi microsoft /proc/version 2>/dev/null
}

detect_mode() {
  if is_apple_silicon; then
    echo mac
  elif has_nvidia_gpu; then
    echo nvidia
  else
    echo cpu
  fi
}

# --- Mac native worker -----------------------------------------------------

model_checkpoint_present() {
  [[ -s "$MODEL_DIR/$CHECKPOINT" ]]
}

setup_mac() {
  is_apple_silicon || die "setup-mac is only for Apple Silicon Macs"
  command -v uv >/dev/null 2>&1 || die "uv is required: https://docs.astral.sh/uv/"
  log "Syncing the app environment (.venv)"
  uv sync --frozen --no-dev
  if [[ ! -x "$MVSEP_VENV/bin/python" ]]; then
    log "Creating the MPS inference environment (.venv-mvsep)"
    uv venv --python 3.10 --seed "$MVSEP_VENV"
  fi
  "$MVSEP_VENV/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
  "$MVSEP_VENV/bin/python" -m pip install --quiet -r requirements-mvsep.txt
  if ! model_checkpoint_present; then
    log "Downloading the MVSep Mega checkpoint (about 1.28 GiB)"
    python3 download_mvsep_mega.py --output-dir "$MODEL_DIR"
  fi
  "$MVSEP_VENV/bin/python" infer_mvsep_mega.py --device mps --check-env
  log "Mac setup complete. Start with: ./fretflow.sh up"
}

mac_worker_pid() {
  [[ -f "$MAC_PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$MAC_PID_FILE")"
  kill -0 "$pid" 2>/dev/null && echo "$pid"
}

start_mac_worker() {
  [[ -x "$MVSEP_VENV/bin/python" ]] || die "missing .venv-mvsep; run ./fretflow.sh setup-mac"
  [[ -x "$ROOT/.venv/bin/python" ]] || die "missing .venv; run ./fretflow.sh setup-mac"
  model_checkpoint_present || die "missing $MODEL_DIR/$CHECKPOINT; run ./fretflow.sh setup-mac"
  if pid="$(mac_worker_pid)"; then
    log "Mac MPS worker already running (pid $pid)"
    return
  fi
  local db_url
  [[ -n "${POSTGRES_PASSWORD:-}" ]] || die "POSTGRES_PASSWORD is not set in .env"
  db_url="postgresql+psycopg://${POSTGRES_USER:-fretflow}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-fretflow}"
  log "Starting the native Mac MPS worker (log: var/worker-mac.log)"
  DATABASE_URL="$db_url" \
  INFERENCE_MODE=real \
  FRETFLOW_JOB_EXECUTION=queue \
  FRETFLOW_ARTIFACT_ROOT="$MAC_ARTIFACTS" \
  FRETFLOW_LOCAL_OWNER_ID=local-user \
  FRETFLOW_MODEL_DIR="$MODEL_DIR" \
  FRETFLOW_MVSEP_SCRIPT="$ROOT/infer_mvsep_mega.py" \
  FRETFLOW_MVSEP_PYTHON="$MVSEP_VENV/bin/python" \
  FRETFLOW_SKIP_MODEL_CHECKSUM="${FRETFLOW_SKIP_MODEL_CHECKSUM:-true}" \
  FRETFLOW_DEVICE="${FRETFLOW_DEVICE:-mps}" \
  FRETFLOW_WORKER_ID=mac-mps \
  PYTORCH_ENABLE_MPS_FALLBACK=1 \
    nohup "$ROOT/.venv/bin/python" -m fretflow.worker serve >>"$MAC_LOG_FILE" 2>&1 &
  echo $! >"$MAC_PID_FILE"
  sleep 2
  mac_worker_pid >/dev/null || die "Mac worker exited; see var/worker-mac.log"
}

stop_mac_worker() {
  local pid
  if pid="$(mac_worker_pid)"; then
    log "Stopping the Mac MPS worker (pid $pid); it finishes the current job first"
    kill -TERM "$pid"
    for _ in $(seq 1 120); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid"
  fi
  rm -f "$MAC_PID_FILE"
}

# --- commands --------------------------------------------------------------

compose() { docker compose "$@"; }

up() {
  local mode="${1:-auto}"
  [[ "$mode" == "auto" ]] && mode="$(detect_mode)"
  mkdir -p "$STATE_DIR"
  ensure_env
  load_env
  log "Mode: $mode"
  case "$mode" in
    nvidia)
      has_nvidia_gpu || die "nvidia-smi cannot see a GPU"
      docker_has_nvidia_runtime \
        || log "warning: Docker lists no nvidia runtime; install the NVIDIA Container Toolkit if the worker fails"
      FRETFLOW_JOB_EXECUTION=queue compose --profile nvidia up -d --build --wait db app gpu-worker
      ;;
    mac)
      is_apple_silicon || die "mac mode needs an Apple Silicon Mac"
      mkdir -p "$MAC_ARTIFACTS"
      FRETFLOW_JOB_EXECUTION=queue FRETFLOW_ARTIFACT_VOLUME="$MAC_ARTIFACTS" \
        compose up -d --build --wait db app
      start_mac_worker
      ;;
    cpu)
      log "No NVIDIA GPU or Apple Silicon found; separation runs on CPU and is slow"
      FRETFLOW_JOB_EXECUTION=queue compose --profile cpu up -d --build --wait db app cpu-worker
      ;;
    fixture)
      FRETFLOW_JOB_EXECUTION=inline compose up -d --build --wait db app
      ;;
    *) die "unknown mode: $mode (use auto, nvidia, mac, cpu, or fixture)" ;;
  esac
  echo "$mode" >"$MODE_FILE"
  log "Open http://127.0.0.1:${APP_PORT:-8000}/"
}

down() {
  load_env
  stop_mac_worker
  # Never pass -v here: that would delete the music library and database.
  compose --profile nvidia --profile cpu down
  rm -f "$MODE_FILE"
}

status() {
  load_env
  log "Detected hardware mode: $(detect_mode)"
  log "Running mode: $(cat "$MODE_FILE" 2>/dev/null || echo none)"
  if pid="$(mac_worker_pid)"; then
    log "Mac MPS worker: running (pid $pid)"
  fi
  compose --profile nvidia --profile cpu ps
}

logs() {
  case "$(cat "$MODE_FILE" 2>/dev/null || echo none)" in
    mac) tail -n 100 -f "$MAC_LOG_FILE" ;;
    nvidia) compose --profile nvidia logs -f gpu-worker ;;
    cpu) compose --profile cpu logs -f cpu-worker ;;
    *) compose logs -f app ;;
  esac
}

case "${1:-}" in
  detect) detect_mode ;;
  setup-mac) setup_mac ;;
  up) up "${2:-auto}" ;;
  down) down ;;
  status) status ;;
  logs) logs ;;
  *)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
