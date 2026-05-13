---
phase: document-specific-quality-policy-second-pass
reviewed: 2026-05-13T05:43:44Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - backend/src/ragstudio/services/reference_metadata.py
  - backend/src/ragstudio/services/reference_unit_assembler.py
  - backend/src/ragstudio/services/chunk_splitter.py
  - backend/src/ragstudio/services/domain_metadata_quality_gate.py
  - backend/src/ragstudio/services/parser_quality_intelligent_gate.py
  - backend/src/ragstudio/services/domain_metadata_ai_suggester.py
  - backend/src/ragstudio/services/hybrid_chunk_search.py
  - backend/src/ragstudio/services/job_quality_warning_service.py
  - backend/src/ragstudio/services/metadata_retrieval_service.py
  - backend/src/ragstudio/services/metadata_json_schema.py
  - backend/src/ragstudio/services/mineru_relationship_builder.py
  - backend/src/ragstudio/services/graph_materialization_service.py
  - backend/src/ragstudio/services/index_lifecycle_service.py
  - backend/src/ragstudio/services/chunk_persistence_service.py
  - backend/src/ragstudio/services/graph_projection_runner.py
  - backend/tests/test_reference_metadata.py
  - backend/tests/test_chunk_splitter.py
  - backend/tests/test_hybrid_chunk_search_arabic.py
  - backend/tests/test_domain_metadata_quality_gate.py
  - backend/tests/test_parser_quality_intelligent_gate.py
  - backend/tests/test_job_quality_warnings.py
  - backend/tests/test_domain_metadata.py
  - backend/tests/test_index_lifecycle_service.py
findings:
  critical: 2
  warning: 1
  info: 0
  total: 3
status: issues_found
---

# Phase document-specific-quality-policy: Second-Pass Code Review Report

**Reviewed:** 2026-05-13T05:43:44Z
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

The previous cross-reference, heading-before-anchor, fallback splitting, top-level optional-script, block-materialization, and evidence-merge regressions now have targeted tests and the main happy paths are improved. The fixes are not fully closed. I found remaining policy-bypass cases in optional-script enforcement and layout block job semantics.

## Critical Issues

### CR-01: BLOCKER - Optional script `block` is bypassed when no required scripts are configured

**File:** `backend/src/ragstudio/services/domain_metadata_quality_gate.py:1212`

**Issue:** `_requires_reference_quality()` only enables the reference-quality materialization path when `profile.required_scripts` is non-empty. A valid policy with only `optional_scripts=["arabic"]` and `missing_optional_script_action="block"` falls into the lightweight `annotate_chunk()` path at lines 208-214, which only merges a parser warning and never writes `quality_action_policy`. The warning carries `action="block_reference_materialization"` from lines 155-174, but the default classifier sets `quality_gate_action="review_warning"` in `parser_quality_intelligent_gate.py:62-67`, and `_parser_warning_blocks_materialization()` then reads `quality_gate_action` before `action` at lines 447-452. Result: the report says `passed_with_warnings`, but `quality_action_policy` is absent, so vector and graph materialization remain allowed.

Manual repro from the current tree:

```text
quality_policy = {"required_scripts": [], "optional_scripts": ["arabic"], "missing_optional_script_action": "block"}
chunk text = "Verse 18:30 English commentary only."
report["status"] = "passed_with_warnings"
chunk.metadata["quality_action_policy"] = None
```

**Fix:** Treat actionable optional scripts as requiring reference quality, and preserve block actions even when they are emitted as parser warnings.

```python
def _requires_reference_quality(self, profile: MetadataQualityProfile) -> bool:
    actionable_optional = (
        bool(profile.optional_scripts)
        and profile.missing_optional_script_action != "no_warning"
    )
    return bool(
        profile.structured_references
        and profile.reference_unit in {"verse", "verse_section", "reference", "hadith", "section"}
        and (profile.required_scripts or actionable_optional)
    )
```

Also update `_parser_warning_blocks_materialization()` to consider both `quality_gate_action` and `action`, including `block_reference_materialization`, then add a regression with optional-only `missing_optional_script_action="block"`.

### CR-02: BLOCKER - `layout_quality_policy` can block materialization while reporting a clean job

**File:** `backend/src/ragstudio/services/parser_quality_intelligent_gate.py:80`

**Issue:** `_classified()` sets `quality_gate_action="block"` when policy `action == "block"`, but line 82 still marks the warning suppressed whenever `warning_level == "info"`. `DomainMetadataQualityGate._apply_parser_quality_action_policy()` correctly blocks vector and graph materialization for that warning, but `parser_quality_summary()` filters suppressed warnings at `backend/src/ragstudio/services/domain_metadata_quality_gate.py:459-465`, and `validate_adapter_chunks()` derives the job status from that empty count at lines 217-220.

The current code therefore accepts this valid policy:

```json
{"action": "block", "warning_level": "info"}
```

and produces a blocked `quality_action_policy` while returning `status="passed"` and `parser_quality.warning_counts={}`. That hides a materialization block from job quality semantics.

**Fix:** A blocking action must never be suppressed. Either reject `action="block"` with `warning_level="info"` during schema validation, or normalize it as an unsuppressed block:

```python
is_block = action == "block" or warning_level == "block"
severity = "block" if action == "block" else warning_level
return {
    **warning,
    "severity": severity,
    "quality_gate_action": "block" if action == "block" else "accepted_recovery" if action == "recover_as_text" else action,
    "suppressed_from_counts": warning_level in INFO_LEVELS and not is_block,
    "quality_gate_reason": reason,
}
```

Add a regression for `layout_action="block", layout_warning_level="info"` asserting `status == "passed_with_warnings"` and a non-empty `parser_quality.warning_counts`.

## Warnings

### WR-01: WARNING - Role-scoped script policies are preserved but never consumed

**File:** `backend/src/ragstudio/services/domain_metadata_quality_gate.py:96`

**Issue:** The schema accepts `quality_policy.required_scripts_by_unit_role` and `quality_policy.optional_scripts_by_unit_role` in `metadata_json_schema.py:268-282`, and the AI suggester preserves them in `domain_metadata_ai_suggester.py:841-856`. `profile_for()` only reads top-level `required_scripts` and `optional_scripts` at lines 96-104; the role maps are not represented in `MetadataQualityProfile` and are never applied in `_reference_record()`. If autosuggest emits role-scoped optional Arabic with `missing_optional_script_action="warn"` or `"block"` but omits top-level `optional_scripts`, the policy is silently ignored.

**Fix:** Either merge role-scoped scripts for the current `reference_unit` into the effective required/optional sets, or strip/reject the role-scoped keys until enforcement exists. Add regressions for role-scoped optional warn and block.

## Open Questions / Assumptions

- I treated `missing_optional_script_action="block"` as an enforceable materialization policy because the schema accepts it and the top-level optional-script test expects `index_vector=false`.
- I treated `action="block"` as higher priority than `warning_level="info"` because otherwise materialization can be blocked while job quality reports clean.
- I did not review unrelated dirty files except where they consume this feature's metadata or quality policy.

## Verification Summary

Commands run:

- `.venv/bin/python -m pytest backend/tests/test_reference_metadata.py::test_derive_reference_metadata_keeps_cross_reference_only_mentions_non_primary backend/tests/test_chunk_splitter.py::test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor backend/tests/test_chunk_splitter.py::test_chunk_splitter_keeps_primary_anchor_after_heading_in_content_list backend/tests/test_chunk_splitter.py::test_chunk_splitter_fallback_uses_primary_anchor_policy_for_inline_references backend/tests/test_hybrid_chunk_search_arabic.py::test_cross_reference_only_inline_reference_does_not_get_reference_exact_boost backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_blocks_layout_policy_materialization backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_blocks_when_optional_script_action_is_block backend/tests/test_domain_metadata.py::test_ai_metadata_merge_preserves_quality_policy_evidence_lists -q` -> 9 passed.
- `git diff --check -- <reviewed feature files/tests>` -> passed.
- Manual optional-only script block repro -> `quality_action_policy` remained absent.
- Manual `layout_action=block, warning_level=info` repro -> materialization blocked while report status stayed `passed`.

---

_Reviewed: 2026-05-13T05:43:44Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
