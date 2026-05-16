---
quick_id: 260516-n1c
status: complete
completed_at: "2026-05-16T12:36:29Z"
task: "Fix Task 5 blocker: retain lexical-expanded exact boost after dedupe"
---

# Summary

Updated retrieval evidence scoring so duplicate-fused candidates keep the
`lexical_expanded_exact` boost when lexical-expanded evidence survives in merged
retrieval passes or match features.

## Verification

- `PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_query_understanding.py -q`
- `PYTHONPATH=$PWD/backend/src .venv/bin/python -m ruff check backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_retrieval_orchestrator.py`
