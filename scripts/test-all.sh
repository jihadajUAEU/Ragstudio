#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop and try again." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is required, but the Docker daemon is not running." >&2
  echo "Start Docker Desktop and try again." >&2
  exit 1
fi

docker compose build backend frontend

backend_run=(
  docker compose run --rm --no-deps
  -e RAGSTUDIO_DATABASE_URL=postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio
  -e RAGSTUDIO_NEO4J_URI=bolt://127.0.0.1:57687
  backend
)

"${backend_run[@]}" python -m pytest backend/tests -q
"${backend_run[@]}" python -m ruff check backend/src backend/tests
"${backend_run[@]}" python -m pyright
docker compose run --rm --no-deps frontend npm run lint
docker compose run --rm --no-deps frontend npm run test -- --run
docker compose run --rm --no-deps frontend npm run build
