#!/usr/bin/env bash
# One-command start for Linux/macOS.
#   ./dev.sh          API on :8000 + Vite dev server on :5173 (hot reload)
#   ./dev.sh --single build the frontend once and serve everything from :8000
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

if [ ! -d backend/.venv ]; then
  echo "Creating backend/.venv ..."
  "$PY" -m venv backend/.venv
  backend/.venv/bin/pip install --upgrade pip
  backend/.venv/bin/pip install -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi

if [ "${1:-}" = "--single" ]; then
  (cd frontend && npm run build)
  echo "Open http://127.0.0.1:8000"
  cd backend && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
fi

(cd backend && .venv/bin/python -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
echo "API  http://127.0.0.1:8000/docs"
echo "App  http://127.0.0.1:5173"
cd frontend && npm run dev -- --host 127.0.0.1
