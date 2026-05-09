#!/usr/bin/env bash
set -euo pipefail

echo "desktop client is deprecated and frozen."
echo "use the Web UI + FastAPI workflow instead:"
echo "  ./start-backend.sh --daemon"
echo "  ./start-frontend.sh --daemon"
echo ""
echo "legacy desktop entry moved to:"
echo "  archive/desktop-legacy/start-desktop.sh"
exit 1
