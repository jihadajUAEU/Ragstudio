#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python -m uvicorn ragstudio.app:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
