---
status: complete
created: 2026-05-16
---

# Fix Bukhari Eid Sacrifice Query ReadTimeout and Wrong Retrieval

Root cause evidence:
- Default fast query for `Which is the hadith saying about offering sacrifice for eid from hadith_bukhari` returns `500 Internal Server Error`.
- Backend stack trace fails at `QueryService._run_runtime_query()` commit with `sqlalchemy.exc.PendingRollbackError`.
- Postgres logs show the session-backed chunk scan was canceled due to the fast response deadline, leaving the transaction requiring rollback.
- With an oversized response budget, the request succeeds slowly but retrieves unrelated Bukhari chunks because lexical scoring rewards common question scaffolding words over answer-bearing terms.
- Follow-up live verification showed the fast path still allowed the LLM-assisted query
  planning stage to be skipped or treated as optional. After making it mandatory for
  religious corpora, the live LLM returned usable target terms but incorrectly set
  `needs_clarification: true`, so the validator rejected a valid plan.

Tasks:
1. [x] Add failing regressions for rollback-safe run persistence and Bukhari topic-query scoring.
2. [x] Fix query persistence so a canceled/invalid retrieval transaction is rolled back and a failed run is still saved instead of returning HTTP 500.
3. [x] Improve English topic scoring/prefiltering so answer-bearing terms like `offering sacrifice` outrank question scaffolding.
4. [x] Make LLM query planning mandatory in auto mode for religious corpora and raise the fast planning timeout to 5000 ms.
5. [x] Accept usable LLM retrieval plans even when the model emits non-canonical labels or wrongly marks `needs_clarification`.
6. [x] Run focused backend tests and live API verification against the Bukhari query.

Verification:
- `.venv/bin/pytest backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunks.py backend/tests/test_retrieval_orchestrator.py::test_fusion_keeps_answer_bearing_metadata_above_graph_neighbors backend/tests/test_runtime_query_service.py::test_query_service_marks_error_type_only_orchestrated_run_failed backend/tests/test_runtime_query_service.py::test_query_service_recovers_when_orchestrator_leaves_session_in_rollback -q`
- `.venv/bin/pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunks.py backend/tests/test_retrieval_orchestrator.py::test_fusion_keeps_answer_bearing_metadata_above_graph_neighbors backend/tests/test_retrieval_orchestrator.py::test_religious_query_requires_llm_planning_in_auto_mode backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_caps_slow_stages backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_defaults_include_mandatory_planner_budget backend/tests/test_runtime_query_service.py::test_query_service_marks_error_type_only_orchestrated_run_failed backend/tests/test_runtime_query_service.py::test_query_service_recovers_when_orchestrator_leaves_session_in_rollback -q`
- `.venv/bin/ruff check backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_runtime_query_service.py backend/tests/test_retrieval_orchestrator.py`
- `.venv/bin/ruff check backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_query_hypothesis_service.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_runtime_query_service.py`
- Live `/api/query` default fast request succeeded in ~9.0s with `Book 13, Hadith 25` as the top source and `timings.query_hypothesis_status=valid`, `timings.query_hypothesis_timeout_ms=5000`.

Follow-up implemented:
1. [x] Extend LLM query planning with capped, normalized `possible_references` hypotheses.
2. [x] Prepend exact-reference retrieval passes from possible references while preserving semantic fallback.
3. [x] Verify possible references against retrieved evidence before they can contribute to answer validation.
4. [x] Set fast-mode final answer budget to `answer_budget_ms=3000` and frontend fast response budget to `15000`.
5. [x] Add Query page `View pathway` drawer showing summary, timeline, planner, retrieval, answer, and raw run details.

Follow-up verification:
- `.venv/bin/pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunks.py backend/tests/test_retrieval_orchestrator.py::test_fusion_keeps_answer_bearing_metadata_above_graph_neighbors backend/tests/test_retrieval_orchestrator.py::test_religious_query_requires_llm_planning_in_auto_mode backend/tests/test_retrieval_orchestrator.py::test_orchestrator_tries_confirmed_hadith_reference_hypothesis_first backend/tests/test_retrieval_orchestrator.py::test_orchestrator_keeps_semantic_fallback_when_reference_hypothesis_is_wrong backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_caps_slow_stages backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_defaults_include_mandatory_planner_budget backend/tests/test_runtime_query_service.py::test_query_service_marks_error_type_only_orchestrated_run_failed backend/tests/test_runtime_query_service.py::test_query_service_recovers_when_orchestrator_leaves_session_in_rollback -q`
- `.venv/bin/ruff check backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/domain_query_expansion_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_query_hypothesis_service.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_runtime_query_service.py`
- `npm test -- query-page.test.tsx`
- `npm run lint`
- `npm run build`
- Playwright smoke at `http://127.0.0.1:5173/query`, screenshot `/tmp/ragstudio-query-pathway.png`, confirmed the pathway drawer opens and shows readable result rows plus `book:13:hadith:25`.
- Live `/api/query` fast request confirmed the planner emitted `possible_references=["book:13:hadith:25"]`, retrieval ran `reference_exact` first, verification confirmed the reference from evidence, and the top source was chunk `1858f80e-7418-4c0e-9811-86248b2fe6d4`.

Code review follow-up:
- Fixed review blocker where hypothesis-origin `reference_exact` candidates could stop semantic fallback before verification.
- Demoted hypothesis-reference candidates so wrong-but-existing references cannot receive exact-reference boosts or outrank semantic evidence.
- Verification now distinguishes `confirmed`, `rejected`, and `not_found`; existing references without target-term support are rejected.
- Parser now accepts top-level string/object `possible_references` and numeric-string `{book, hadith}` planner objects.
- English prefilter now remains a priority prefix but scores the full scoped chunk set to preserve recall.

Review follow-up verification:
- `.venv/bin/pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_chunks.py::test_search_scores_full_scope_after_english_prefilter backend/tests/test_retrieval_orchestrator.py::test_orchestrator_tries_confirmed_hadith_reference_hypothesis_first backend/tests/test_retrieval_orchestrator.py::test_orchestrator_keeps_semantic_fallback_when_reference_hypothesis_is_wrong -q`
- `.venv/bin/pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunks.py backend/tests/test_retrieval_orchestrator.py::test_fusion_keeps_answer_bearing_metadata_above_graph_neighbors backend/tests/test_retrieval_orchestrator.py::test_religious_query_requires_llm_planning_in_auto_mode backend/tests/test_retrieval_orchestrator.py::test_orchestrator_tries_confirmed_hadith_reference_hypothesis_first backend/tests/test_retrieval_orchestrator.py::test_orchestrator_keeps_semantic_fallback_when_reference_hypothesis_is_wrong backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_caps_slow_stages backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_defaults_include_mandatory_planner_budget backend/tests/test_runtime_query_service.py::test_query_service_marks_error_type_only_orchestrated_run_failed backend/tests/test_runtime_query_service.py::test_query_service_recovers_when_orchestrator_leaves_session_in_rollback -q`
- `.venv/bin/ruff check backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/domain_query_expansion_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/retrieval_fusion.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_query_hypothesis_service.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_runtime_query_service.py backend/tests/test_chunks.py`
- `npm test -- query-page.test.tsx`
- `npm run lint`
- `npm run build`
