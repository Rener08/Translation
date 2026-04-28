#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PID_FILE="$ROOT_DIR/tmp/backend.pid"
LOG_FILE="$ROOT_DIR/backend_run.log"
DAEMON_MODE="${1:-}"

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  python3.11 -m venv "$BACKEND_DIR/.venv"
fi

mkdir -p "$ROOT_DIR/tmp"

is_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

backend_healthy() {
  curl -fsS -m 2 "http://127.0.0.1:8000/health" >/dev/null 2>&1
}

UVICORN_BASE_CMD=(
  "$BACKEND_DIR/.venv/bin/python"
  -m
  uvicorn
  app.main:app
  --app-dir
  "$BACKEND_DIR"
  --host
  127.0.0.1
  --port
  8000
)

UVICORN_DEV_CMD=(
  "${UVICORN_BASE_CMD[@]}"
  --reload
)

if [ "$DAEMON_MODE" = "--daemon" ]; then
  if [ -f "$PID_FILE" ]; then
    EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$EXISTING_PID" ] && is_alive "$EXISTING_PID" && backend_healthy; then
      echo "✅ Backend is already running on http://127.0.0.1:8000 (pid: $EXISTING_PID)"
      exit 0
    fi
    rm -f "$PID_FILE"
  fi

  if backend_healthy; then
    RUNNING_PID="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$RUNNING_PID" ]; then
      echo "$RUNNING_PID" > "$PID_FILE"
      echo "✅ Backend is already running on http://127.0.0.1:8000 (pid: $RUNNING_PID)"
      exit 0
    fi
  fi

  PORT_PIDS="$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$PORT_PIDS" ]; then
    echo "❌ Port 8000 is already in use by another process:"
    lsof -nP -iTCP:8000 -sTCP:LISTEN || true
    echo "Tip: stop that process and retry."
    exit 1
  fi

  : > "$LOG_FILE"
  # Keep daemon mode stable: avoid reloader subprocess tree in background.
  # Prefer setsid so the backend is detached from the caller's session.
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "${UVICORN_BASE_CMD[@]}" >>"$LOG_FILE" 2>&1 < /dev/null &
  else
    nohup "${UVICORN_BASE_CMD[@]}" >>"$LOG_FILE" 2>&1 < /dev/null &
  fi
  BACKEND_PID=$!
  echo "$BACKEND_PID" > "$PID_FILE"

  for _ in $(seq 1 30); do
    if backend_healthy; then
      echo "✅ Backend started in background: http://127.0.0.1:8000 (pid: $BACKEND_PID)"
      echo "📝 Log file: $LOG_FILE"
      exit 0
    fi
    sleep 1
  done

  echo "❌ Backend failed to become healthy within 30s."
  echo "Last backend logs:"
  tail -n 80 "$LOG_FILE" || true
  exit 1
fi

exec "${UVICORN_DEV_CMD[@]}"
