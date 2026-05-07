#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHONPATH=backend/src python - <<'PY'
import json

from ragstudio.app import create_app

schema = create_app().openapi()
print(json.dumps(schema))
PY
