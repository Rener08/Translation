#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PID_FILE="$ROOT_DIR/tmp/frontend.pid"
LOG_FILE="$ROOT_DIR/frontend_run.log"
NODE22_BIN="/opt/homebrew/opt/node@22/bin"
NODE22_EXEC="$NODE22_BIN/node"
NODE22_SIMDJSON_DYLIB="/opt/homebrew/opt/simdjson/lib/libsimdjson.30.dylib"
BREW_NODE_BIN="/opt/homebrew/bin"
DAEMON_MODE="${1:-}"

mkdir -p "$ROOT_DIR/tmp"

cd "$FRONTEND_DIR"

if [ -x "$NODE22_EXEC" ] && [ -f "$NODE22_SIMDJSON_DYLIB" ] && "$NODE22_EXEC" -v >/dev/null 2>&1; then
  export PATH="$NODE22_BIN:$PATH"
elif [ -x "$BREW_NODE_BIN/node" ] && "$BREW_NODE_BIN/node" -v >/dev/null 2>&1; then
  export PATH="$BREW_NODE_BIN:$PATH"
  echo "ℹ️ using Homebrew default node from $BREW_NODE_BIN"
else
  echo "⚠️ node@22 is unavailable (missing dylib or broken link), falling back to current PATH node."
fi

if [ ! -f "$FRONTEND_DIR/node_modules/next/dist/bin/next" ]; then
  npm install
fi

NODE_MAJOR_VERSION="$(node -p "Number.parseInt(process.versions.node.split('.')[0] ?? '0', 10)")"
CLEANED_NODE_OPTIONS="$(printf '%s' "${NODE_OPTIONS:-}" | sed -E 's/(^| )--localstorage-file(=[^ ]*)?( |$)/ /g' | xargs)"
if [ "${NODE_MAJOR_VERSION:-0}" -ge 25 ]; then
  LOCAL_STORAGE_FILE="/tmp/youtube-translator-next-dev.localstorage"
  # Node 25 + Next dev can expose a broken server localStorage unless a concrete file is set.
  # Also scrub any stale/invalid --localstorage-file value from inherited NODE_OPTIONS.
  if [ -n "$CLEANED_NODE_OPTIONS" ]; then
    export NODE_OPTIONS="$CLEANED_NODE_OPTIONS --localstorage-file=$LOCAL_STORAGE_FILE"
  else
    export NODE_OPTIONS="--localstorage-file=$LOCAL_STORAGE_FILE"
  fi
elif [ -n "$CLEANED_NODE_OPTIONS" ]; then
  export NODE_OPTIONS="$CLEANED_NODE_OPTIONS"
else
  unset NODE_OPTIONS || true
fi

is_pid_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

frontend_healthy() {
  curl -sSI -m 2 "http://127.0.0.1:3000" 2>/dev/null | tr '[:upper:]' '[:lower:]' | grep -q "x-powered-by: next.js"
}

if [ "$DAEMON_MODE" = "--daemon" ] && [ -f "$PID_FILE" ]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$EXISTING_PID" ] && is_pid_alive "$EXISTING_PID" && frontend_healthy; then
    echo "✅ Frontend is already running on http://localhost:3000 (pid: $EXISTING_PID)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

PORT_PIDS="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PORT_PIDS" ]; then
  if frontend_healthy; then
    if [ "$DAEMON_MODE" = "--daemon" ]; then
      RUNNING_PID="$(echo "$PORT_PIDS" | head -n 1)"
      if [ -n "$RUNNING_PID" ]; then
        echo "$RUNNING_PID" > "$PID_FILE"
      fi
    fi
    echo "✅ Frontend is already running on http://localhost:3000"
    exit 0
  fi

  echo "❌ Port 3000 is already in use by another process:"
  lsof -nP -iTCP:3000 -sTCP:LISTEN || true
  echo "Tip: stop that process or run frontend on another port."
  exit 1
fi

if [ "$DAEMON_MODE" = "--daemon" ]; then
  : > "$LOG_FILE"
  nohup node ./scripts/run-next.mjs dev --hostname 0.0.0.0 --port 3000 >>"$LOG_FILE" 2>&1 &
  FRONTEND_PID=$!
  echo "$FRONTEND_PID" > "$PID_FILE"

  for _ in $(seq 1 45); do
    if frontend_healthy; then
      echo "✅ Frontend started in background: http://localhost:3000 (pid: $FRONTEND_PID)"
      echo "📝 Log file: $LOG_FILE"
      exit 0
    fi
    sleep 1
  done

  echo "❌ Frontend failed to become healthy within 45s."
  echo "Last frontend logs:"
  tail -n 120 "$LOG_FILE" || true
  exit 1
fi

exec node ./scripts/run-next.mjs dev --hostname 0.0.0.0 --port 3000
