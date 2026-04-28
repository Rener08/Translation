#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID_FILE="$ROOT_DIR/tmp/backend.pid"
FRONTEND_PID_FILE="$ROOT_DIR/tmp/frontend.pid"

stop_by_pid_file() {
  local name="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    echo "ℹ️ $name pid file not found."
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -z "$pid" ]; then
    rm -f "$pid_file"
    echo "ℹ️ $name pid file was empty."
    return
  fi

  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "🛑 Stopped $name (pid: $pid)"
  else
    echo "ℹ️ $name process not running (stale pid: $pid)"
  fi

  rm -f "$pid_file"
}

stop_by_port() {
  local name="$1"
  local port="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return
  fi

  echo "ℹ️ Found $name listener(s) on port $port: $pids"
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done

  sleep 1
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null || true
    done
  fi

  echo "🧹 Cleared $name listeners on port $port"
}

stop_by_pid_file "backend" "$BACKEND_PID_FILE"
stop_by_pid_file "frontend" "$FRONTEND_PID_FILE"
stop_by_port "backend" "8000"
stop_by_port "frontend" "3000"

echo "✅ Stop command completed."
