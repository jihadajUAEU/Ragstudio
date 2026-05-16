---
status: complete
quick_id: 260516-mnt
slug: fix-task-4-review-warning-preserve-lexic
---

Implemented a scoped fix for preserving lexical expansion match type from
domain expansion passes through metadata retrieval match features.

Validation:
- `PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_domain_query_expansion_service.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_query_understanding.py -q`
- `PYTHONPATH=$PWD/backend/src .venv/bin/python -m ruff check backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/domain_query_expansion_service.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_query_understanding.py`
