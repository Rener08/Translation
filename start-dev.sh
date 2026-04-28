#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

"$ROOT_DIR/start-backend.sh" --daemon
"$ROOT_DIR/start-frontend.sh" --daemon

echo ""
echo "✅ Dev services are up:"
echo "   - frontend: http://localhost:3000"
echo "   - backend : http://127.0.0.1:8000/health"
echo ""
echo "Useful commands:"
echo "   ./status-dev.sh"
echo "   ./stop-dev.sh"
echo "   tail -f frontend_run.log"
echo "   tail -f backend_run.log"

echo ""
"$ROOT_DIR/status-dev.sh"
