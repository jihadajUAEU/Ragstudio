#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python -m pytest backend/tests -q
python -m ruff check backend/src backend/tests
python -m pyright
cd frontend
npm run lint
npm run test -- --run
npm run build
