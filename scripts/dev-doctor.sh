#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

PYTHON_BIN=""
if [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
fi

echo "== Python =="
if [ -n "$PYTHON_BIN" ]; then
  "$PYTHON_BIN" --version
  "$PYTHON_BIN" - <<'PY'
import importlib.util

for module_name in ("fastapi", "uvicorn", "httpx", "yaml"):
    print(f"{module_name}: {'ok' if importlib.util.find_spec(module_name) else 'missing'}")
PY
else
  echo "python: not found"
fi

echo
echo "== Node =="
if command -v node >/dev/null 2>&1; then
  node --version
else
  echo "node: not found"
fi

echo
echo "== Env =="
if [ -n "$PYTHON_BIN" ]; then
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" - <<'PY'
from pathlib import Path

from app.config import ROOT_DIR, get_env_str, get_settings, resolve_yt_dlp_cookie_config

settings = get_settings()
cookie_config = resolve_yt_dlp_cookie_config()
cookie_path = cookie_config.effective_path

print("ROOT_DIR:", ROOT_DIR)
print("DEPLOYMENT_PROFILE:", settings.deployment_profile)
print("TRANSLATION_PROVIDER:", get_env_str("TRANSLATION_PROVIDER") or "(empty)")
print("NEXT_PUBLIC_API_BASE_URL:", get_env_str("NEXT_PUBLIC_API_BASE_URL") or "(empty)")
print("NEXT_PUBLIC_API_AUTH_TOKEN_SET:", bool(get_env_str("NEXT_PUBLIC_API_AUTH_TOKEN")))
print("YTDLP_COOKIES_FILE:", get_env_str("YTDLP_COOKIES_FILE") or "(empty)")
print("YTDLP_COOKIES_FROM_BROWSER:", get_env_str("YTDLP_COOKIES_FROM_BROWSER") or "(empty)")
print("YTDLP_ENABLE_DEFAULT_COOKIES_FILE:", settings.enable_default_cookies_file)
print("YTDLP_COOKIE_MODE:", cookie_config.mode)
print("YTDLP_COOKIE_CONFIGURED:", cookie_config.configured)
print("YTDLP_COOKIE_ACTIVE_FOR_YT_DLP:", cookie_config.active_for_yt_dlp)
print("YTDLP_COOKIE_PATH:", cookie_path.as_posix() if cookie_path else "(none)")
print("YTDLP_COOKIE_EXISTS:", bool(cookie_path and cookie_path.exists()))
print("JOB_QUEUE_DB_PATH:", settings.job_queue_db_path.as_posix())
print("ACCOUNT_QUOTA_DB_PATH:", settings.account_quota_db_path.as_posix())
PY
  )
fi

echo
echo "== Ports =="
if command -v lsof >/dev/null 2>&1; then
  lsof -nP -iTCP:8000 -sTCP:LISTEN || true
  lsof -nP -iTCP:8002 -sTCP:LISTEN || true
  lsof -nP -iTCP:3000 -sTCP:LISTEN || true
else
  echo "lsof: not available"
fi

echo
echo "== Backend health =="
for url in "http://127.0.0.1:8000/health" "http://127.0.0.1:8000/readyz"; do
  if command -v curl >/dev/null 2>&1 && curl -fsS "$url" >/dev/null; then
    echo "$url: ok"
  else
    echo "$url: not reachable"
  fi
done

echo
echo "== Frontend build hint =="
if [ -f "$FRONTEND_DIR/package.json" ]; then
  echo "frontend: present"
else
  echo "frontend: missing"
fi
