---
phase: document-specific-quality-policy
reviewed: 2026-05-13T04:56:57Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - backend/src/ragstudio/api/routes/domain_profiles.py
  - backend/src/ragstudio/services/metadata_json_schema.py
  - backend/src/ragstudio/services/domain_metadata_ai_suggester.py
  - backend/src/ragstudio/services/reference_metadata.py
  - backend/src/ragstudio/services/reference_unit_assembler.py
  - backend/src/ragstudio/services/domain_metadata_quality_gate.py
  - backend/src/ragstudio/services/parser_quality_intelligent_gate.py
  - backend/src/ragstudio/services/job_quality_warning_service.py
  - backend/src/ragstudio/services/metadata_retrieval_service.py
  - backend/src/ragstudio/services/chunk_splitter.py
  - backend/src/ragstudio/services/document_parser_service.py
  - backend/src/ragstudio/services/mineru_client.py
  - backend/src/ragstudio/services/parser_normalization.py
  - backend/src/ragstudio/services/domain_metadata_service.py
  - backend/src/ragstudio/services/hybrid_chunk_search.py
  - backend/src/ragstudio/services/mineru_relationship_builder.py
  - backend/src/ragstudio/services/graph_materialization_service.py
  - backend/tests/test_domain_metadata.py
  - backend/tests/test_domain_metadata_quality_gate.py
  - backend/tests/test_chunk_splitter.py
  - backend/tests/test_parser_quality_intelligent_gate.py
  - backend/tests/test_job_quality_warnings.py
  - backend/tests/test_document_parser_service.py
  - docs/workflows.md
  - docs/user-guide.md
  - docs/superpowers/plans/2026-05-13-document-specific-quality-policy.md
findings:
  critical: 3
  warning: 3
  info: 0
  total: 6
status: issues_found
---

# Phase document-specific-quality-policy: Code Review Report

**Reviewed:** 2026-05-13T04:56:57Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Reviewed the current working tree changes for document-specific quality and script policy, centered on autosuggest schema preservation, primary-anchor assembly, quality gates, parser warning classification, retrieval quality metadata, and related tests/docs.

The implementation adds the expected schema sections and focused happy-path tests, but there are still policy-boundary defects. The largest risk is that inline cross-references are still written into the same `reference_metadata.references` list used by exact-reference retrieval and graph materialization, so a commentary chunk can become the exact top hit for a citation it only mentions in passing. A second data-loss bug drops the first answerable primary-anchor unit when a heading precedes the first anchor in the same parser block.

## Critical Issues

### CR-01: BLOCKER - Inline cross-references are still treated as primary exact-reference hits

**File:** `backend/src/ragstudio/services/reference_unit_assembler.py:287`

**Issue:** `ReferenceUnitAssembler._reference_metadata()` calls `semantics.derive_reference_metadata(text, ...)` for the whole assembled unit. `derive_reference_metadata()` stores every matched reference into `reference_metadata.references` at `backend/src/ragstudio/services/reference_metadata.py:272`, including inline cross-references that policy marked as `cross_reference_only`. `HybridChunkSearch` then gives `reference_exact = 100.0` when the query reference is in that list at `backend/src/ragstudio/services/hybrid_chunk_search.py:60`, and `MinerURelationshipBuilder`/graph materialization also treat every item in that list as a normal `references` edge.

This violates the new policy contract: an English Tafseer section anchored by `Verse 18:30` but mentioning `25:75-76` can become an exact-reference result for `25:75`, even though `25:75` is not the answerable unit. I confirmed this with a local score check: a chunk with `references=["18:30", "25:75"]` receives `reference_exact=100.0` for query `25:75`.

**Fix:** Separate primary anchors from inline cross-references in persisted metadata. For example, store only the canonical answerable anchor in `reference_metadata.references`, and store inline mentions under `reference_metadata.cross_references` or `relationship_metadata.cross_references`. Exact-reference retrieval and primary graph/reference nodes should use the primary list only; cross-reference edges can consume the cross-reference list explicitly. Add a regression asserting that a `cross_reference_only` inline citation does not receive a `reference_exact` boost.

### CR-02: BLOCKER - Primary-anchor units can be dropped when a heading precedes the first anchor

**File:** `backend/src/ragstudio/services/reference_metadata.py:217`

**Issue:** `split_primary_anchor_units()` preserves leading text by prepending it to the first anchor unit at `backend/src/ragstudio/services/reference_metadata.py:255`, but `extract_primary_anchor_references()` only searches the first line of the block at `backend/src/ragstudio/services/reference_metadata.py:224`. When a parser block starts with a heading or page title followed by `Verse 18:30`, the split unit begins with the heading, the anchor is no longer on the first line, and `ReferenceUnitAssembler` treats the block as unassigned/provenance-only at `backend/src/ragstudio/services/reference_unit_assembler.py:85`.

I reproduced this locally with one block containing `Commentary heading\n\nVerse 18:30 body mentions 25:75-76`; assembly returned `[(None, 'reference_provenance', None)]`. That loses an answerable reference unit during indexing.

**Fix:** Search for the configured primary anchor at the first anchor match in the block, not only on the first line, while still preventing inline references from starting units. One concrete path is to have `split_primary_anchor_units()` return the matched reference with each unit, or let `extract_primary_anchor_references()` search the whole split unit and reject matches only after non-heading body text. Add a regression with a heading before the first primary anchor.

### CR-03: BLOCKER - `block` layout policy does not block indexing or materialization

**File:** `backend/src/ragstudio/services/parser_quality_intelligent_gate.py:76`

**Issue:** `layout_quality_policy` allows `action: "block"` and `warning_level: "block"`, but `_classified()` only copies those values into warning metadata and sets `suppressed_from_counts` from `warning_level == "info"`. `DomainMetadataQualityGate.validate_adapter_chunks()` then only turns non-suppressed warning counts into `passed_with_warnings` at `backend/src/ragstudio/services/domain_metadata_quality_gate.py:194`; it never fails the gate or sets a blocking `quality_action_policy` for parser recovery warnings.

That means a document policy can explicitly say recovered text is a true blocker and the chunk still gets indexed and projected as long as the warning remains only metadata. The new tests cover accepted recovery, but not blocking recovery.

**Fix:** Define enforcement semantics for parser recovery actions. If `action == "block"` or `warning_level == "block"`, the quality gate should either raise `DomainMetadataQualityGateError` or mark affected chunks with `quality_action_policy.index_vector=false` and `project_graph=false`. Add tests for `action=block` and `warning_level=block`.

## Warnings

### WR-01: WARNING - Markdown/fallback splitting ignores the primary-anchor policy

**File:** `backend/src/ragstudio/services/chunk_splitter.py:393`

**Issue:** The fallback `_reference_unit_sections()` path still uses `profile.semantics.split_reference_units()` at line 409, which splits on every reference match. It does not use `split_primary_anchor_units()` for `inline_reference_policy == "cross_reference_only"`, and it does not include `verse_section` in the allowed chunk units at lines 401-407. Any path that reaches fallback markdown splitting can still split inline citations into separate answerable chunks, or fail to split a document whose primary anchor unit is only `verse_section`.

**Fix:** Apply the same primary-anchor semantics in `_reference_unit_sections()` that `ReferenceUnitAssembler` uses for content-list blocks. Include `verse_section` in the supported reference units, use `split_primary_anchor_units()` when inline references are cross-reference-only, and add a non-content-list regression with `Verse 18:30 ... 25:75-76 ... Verse 18:32`.

### WR-02: WARNING - Optional script actions are accepted but never enforced

**File:** `backend/src/ragstudio/services/domain_metadata_quality_gate.py:140`

**Issue:** `MetadataQualityProfile` carries `optional_scripts` and `missing_optional_script_action`, but warning generation only iterates `profile.required_scripts` in `warnings_for_text()` and `_reference_record()` at `backend/src/ragstudio/services/domain_metadata_quality_gate.py:765`. As a result, `missing_optional_script_action: "warn"` or `"block"` is silently ignored, and the role-specific script maps preserved from autosuggest are not consulted for reference records.

**Fix:** Either remove unsupported actions from the accepted schema or implement them. A concrete fix is to compute optional-missing scripts separately, emit info/warn/block records according to `missing_optional_script_action`, and keep `no_warning` as the default suppression path for secondary-source documents. Add tests for optional `warn` and optional `block`.

### WR-03: WARNING - Baseline merge can erase quality-policy evidence lists

**File:** `backend/src/ragstudio/services/domain_metadata_ai_suggester.py:581`

**Issue:** `_deep_merge_dicts()` merges any two lists through `_merge_unique_strings()`. That works for string lists, but `quality_policy.evidence` is a list of objects. If both a baseline profile and the AI suggestion contain evidence, the merge filters out every dict and replaces the evidence list with `[]`, losing the audit trail that justified the policy.

**Fix:** Merge list values by shape. Use string-only merging only when both lists contain strings; for object lists such as `quality_policy.evidence`, either prefer the AI list, append/dedupe by stable JSON serialization, or preserve the baseline list when the AI value is empty. Add a baseline merge regression for `quality_policy.evidence`.

## Open Questions / Assumptions

- I treated `cross_reference_only` as meaning "do not use inline citations for primary exact-reference retrieval or primary graph materialization." If cross-reference retrieval is desired, it should be an explicit lower-priority retrieval feature with separate metadata.
- I assumed `block` in `layout_quality_policy` is intended to affect materialization, not just display a label. The current schema and prompt present it as a real policy action.
- I did not review unrelated dirty files except where they directly consume this feature, such as chunk splitting, hybrid search, relationship building, graph materialization, and parser option plumbing.

## Verification Summary

Commands run:

- `.venv/bin/python -m pytest backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_domain_structure_quality_and_layout_policy backend/tests/test_domain_metadata.py::test_ai_metadata_normalizes_document_specific_quality_policies backend/tests/test_chunk_splitter.py::test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_allows_tafseer_commentary_when_optional_arabic_is_missing backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_suppresses_accepted_recovered_text_warning_counts backend/tests/test_parser_quality_intelligent_gate.py backend/tests/test_job_quality_warnings.py::test_job_quality_warnings_keeps_suppressed_recovery_visible_but_uncounted -q` -> 9 passed.
- `git diff --check -- <reviewed policy files/tests/docs>` -> passed.
- Manual reference assembly check with a heading before `Verse 18:30` -> reproduced provenance-only output.
- Manual hybrid scoring check for inline `25:75` in `reference_metadata.references` -> reproduced `reference_exact=100.0`.

---

_Reviewed: 2026-05-13T04:56:57Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
