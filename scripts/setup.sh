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
