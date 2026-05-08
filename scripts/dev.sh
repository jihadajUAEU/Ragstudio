#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export RAGSTUDIO_DATABASE_URL="${RAGSTUDIO_DATABASE_URL:-postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio}"
export RAGSTUDIO_NEO4J_URI="${RAGSTUDIO_NEO4J_URI:-bolt://127.0.0.1:57687}"
export RAGSTUDIO_NEO4J_USERNAME="${RAGSTUDIO_NEO4J_USERNAME:-neo4j}"
export RAGSTUDIO_NEO4J_PASSWORD="${RAGSTUDIO_NEO4J_PASSWORD:-ragstudio-password}"
python -m uvicorn ragstudio.app:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
