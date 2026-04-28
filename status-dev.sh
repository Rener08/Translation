#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID_FILE="$ROOT_DIR/tmp/backend.pid"
FRONTEND_PID_FILE="$ROOT_DIR/tmp/frontend.pid"

print_status() {
  local name="$1"
  local url="$2"
  local pid_file="$3"
  local port="$4"
  local expected_header="${5:-}"

  local status="down"
  local pid_text="none"

  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      pid_text="$pid"
    else
      pid_text="stale"
    fi
  fi

  if [ -n "$expected_header" ]; then
    local headers
    headers="$(curl -sSI -m 2 "$url" || true)"
    if [ -n "$headers" ] && printf '%s' "$headers" | tr '[:upper:]' '[:lower:]' | grep -q "$expected_header"; then
      status="up"
    fi
  else
    local http_code
    http_code="$(curl -sS -m 2 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true)"
    if [ "$http_code" = "200" ]; then
      status="up"
    fi
  fi

  if [ "$status" = "up" ] && [ "$pid_text" = "none" ]; then
    local detected_pid
    detected_pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$detected_pid" ]; then
      pid_text="$detected_pid"
    fi
  fi

  printf "%-9s : %-4s (pid: %s) %s\n" "$name" "$status" "$pid_text" "$url"
}

print_status "backend" "http://127.0.0.1:8000/health" "$BACKEND_PID_FILE" "8000"
print_status "frontend" "http://127.0.0.1:3000" "$FRONTEND_PID_FILE" "3000" "x-powered-by: next.js"
