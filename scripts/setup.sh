#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python -m pip install -e "backend[dev]"
npm --prefix frontend install
