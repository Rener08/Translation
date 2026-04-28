#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_VENV="$ROOT_DIR/.desktop-venv"
PYTHON_FALLBACK="${PYTHON_FALLBACK:-python3.11}"

if ! command -v "$PYTHON_FALLBACK" >/dev/null 2>&1; then
  PYTHON_FALLBACK="python3"
fi

if [ ! -d "$DESKTOP_VENV" ]; then
  "$PYTHON_FALLBACK" -m venv "$DESKTOP_VENV"
fi

PYTHON_BIN="$DESKTOP_VENV/bin/python"
PIP_BIN="$DESKTOP_VENV/bin/pip"

if ! "$PYTHON_BIN" -c "import PyQt6, requests" >/dev/null 2>&1; then
  "$PIP_BIN" install -q -r "$ROOT_DIR/requirements-desktop.txt"
fi

export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1

exec "$PYTHON_BIN" "$ROOT_DIR/desktop_app.py" "$@"
