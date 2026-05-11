#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDF_PATH="${PDF_PATH:-/Users/meet/Downloads/quran_arabic_english.pdf}"

echo "Using API: ${BASE_URL}"
echo "Using PDF: ${PDF_PATH}"

echo "Creating variants..."
python3 - "$SAMPLE_DIR/quran-variants.json" "$BASE_URL" <<'PY'
import json
import sys
import urllib.error
import urllib.request

variants_path, base_url = sys.argv[1], sys.argv[2]
with open(variants_path, "r", encoding="utf-8") as handle:
    variants = json.load(handle)

for variant in variants:
    request = urllib.request.Request(
        f"{base_url}/api/variants",
        data=json.dumps(variant).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            print(f"created variant: {payload['name']} ({payload['id']})")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"variant create failed for {variant['name']}: HTTP {exc.code} {detail}", file=sys.stderr)
        raise
PY

echo "Importing evaluation set..."
curl -fsS \
  -F "file=@${SAMPLE_DIR}/quran-evaluation-set.json;type=application/json" \
  "${BASE_URL}/api/evaluation-sets/import?name=Quran%20reference%20and%20phrase%20evaluation" \
  | python3 -m json.tool

echo
echo "Optional upload command:"
echo "curl -fsS -F 'parser_mode=mineru_strict' -F 'domain_metadata=<${SAMPLE_DIR}/quran-domain-metadata.json' -F 'file=@${PDF_PATH};type=application/pdf' '${BASE_URL}/api/documents'"
echo
echo "Now open the UI, select the document, imported evaluation set, and variants, then run the experiment."
