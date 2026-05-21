# Warning Count and Vision Recovery Fix Plan

## Problem

The Documents jobs UI can show these values for the same completed index job:

- `Parser warning details · 4 types · 2710 grouped warnings`
- `reference_unit_missing_expected_script=228`
- `counted_affected_chunks=228`
- `display_rows=2482`

This makes it look like `reference_unit_missing_expected_script` was fixed by the vision fallback while the UI still reports the same warning. The current code path does not prove that. It records unresolved missing-script reference units as targeted vision recovery requests after local repair fails.

## Root Cause Trace

1. `DomainMetadataQualityGate.parser_quality_summary()` filters out warnings with `suppressed_from_counts` or `severity=info` and counts one code per affected chunk. This produces the counted warning totals such as `reference_unit_missing_expected_script=228`.

2. `DomainMetadataQualityGate.parser_quality_details()` groups raw parser warnings for display and currently increments `warning_count` for every warning row. It does not apply the same counted-warning filter and does not dedupe generic/reference-specific missing-script duplicates.

3. `JobQualityWarningService.details()` expands persisted parser warnings from chunks into modal rows. It dedupes reference-less `reference_unit_missing_expected_script` warnings when a reference-specific warning exists, so `display_rows` can be lower than the job-card grouped warning total.

4. `QualityRepairPass.apply_pre_quality_repairs()` can actually fix missing script only when the missing script exists in same-chunk provenance blocks.

5. `QualityRepairPass.apply_post_quality_repairs()` does not execute vision OCR. It annotates remaining missing-script records with `targeted_vision_recovery_requests` and marks warning rows with `vision_recovery_required=True`.

## Working Behavior To Preserve

- Accepted recovery evidence should stay visible in the inspect modal but must remain uncounted.
- Pure layout noise downgraded to info should stay visible as audit evidence but not contribute to parser warning counts.
- Same-chunk provenance repair should clear `reference_unit_missing_expected_script` when the required script is actually recovered into chunk text.
- Genuine English-only or Arabic-missing reference units should continue to warn until recovery actually adds the missing script.

## Fix Plan

### 1. Align Job-Card Warning Group Counts With Counted Semantics

Update `DomainMetadataQualityGate.parser_quality_details()` to return both raw and counted values:

- `raw_warning_count`
- `raw_chunk_count`
- `warning_count`
- `chunk_count`
- optional `audit_row_count`

`warning_count` and `chunk_count` should use the same counted-warning predicate as `parser_quality_summary()`: skip `suppressed_from_counts=True` and `severity=info`.

Keep raw counts available for diagnostics, but do not label raw rows as parser warnings in the primary UI copy.

### 2. Dedupe Missing-Script Details Consistently

Move the existing `JobQualityWarningService._dedupe_parser_warnings()` behavior into a shared helper or apply equivalent logic in `parser_quality_details()`.

The specific rule to preserve:

- If a chunk has both a generic `reference_unit_missing_expected_script` warning and a reference-specific warning for the same expected script, count/display the reference-specific warning as the actionable row.

### 3. Rename UI Metrics So The Meaning Is Explicit

Update `DocumentsPage` labels:

- `counted_affected_chunks` -> `counted_warning_chunks`
- `display_rows` -> `warning_detail_rows`
- job-card parser details should say `counted warnings` when showing counted totals.
- if raw audit rows are shown, label them `audit rows` or `raw parser rows`.

Do not make the job card and inspect panel use the same number unless they are actually measuring the same thing.

### 4. Make Targeted Vision Recovery Status Honest

Add explicit status fields to the repair report and warning rows:

- `vision_recovery_status`: `requested`, `executed`, `succeeded`, `failed`, or `not_configured`
- `vision_recovery_required`: true only when still unresolved after local repair
- `recovery_source`: set to `vision_model:<model>` only when OCR actually ran

The UI should render `targeted vision recovery requested` when the post-quality layer only created a request.

### 5. Execute Targeted Vision Recovery Or Rename It As Pending

Pick one implementation path:

- Short-term: keep the current behavior, but rename all user-facing text from "vision fallback fixed" to "targeted vision recovery requested" and do not imply resolution.
- Full fix: after post-quality repair creates targeted requests, run a targeted recovery pass against the relevant page/image evidence, append recovered text to the affected reference unit, rerun reference quality annotation, and only then clear `reference_unit_missing_expected_script`.

The full fix needs one execution boundary in `IndexLifecycleService` after initial quality annotation and before chunk persistence.

### 6. Add Regression Tests

Backend tests:

- `parser_quality_details` excludes suppressed/info warnings from counted totals while preserving raw/audit totals.
- `parser_quality_details` dedupes generic missing-script rows when reference-specific rows exist.
- post-quality repair with no executable vision pass leaves `reference_unit_missing_expected_script` counted and marks `vision_recovery_status=requested`.
- targeted vision execution that adds Arabic text reruns quality and clears `reference_unit_missing_expected_script`.

Frontend tests:

- job card shows counted parser warnings, not raw grouped warning rows.
- inspect panel labels counted chunks and detail rows distinctly.
- warning row with `vision_recovery_status=requested` is not shown as fixed.
- accepted recovery rows remain visible but uncounted.

## Verification Commands

Run focused backend tests:

```powershell
$env:PYTHONPATH='backend/src'
python -m pytest backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_job_quality_warnings.py backend/tests/test_parser_normalization.py
```

Run focused frontend tests:

```powershell
cmd /c npm --prefix frontend test -- documents-page.test.tsx
```

Then manually verify the quran job:

- job card counted warning total matches `parser_quality.warning_counts`
- inspect panel `counted_warning_chunks` remains `228` until actual vision recovery succeeds
- detail rows no longer imply `228` was solved unless recovered text was persisted and quality reran

## Open Decision

Decide whether the next implementation should be the short-term honest-labeling fix or the full targeted-vision execution fix. The short-term fix prevents misleading UI immediately. The full fix is the real product behavior needed to resolve the remaining `228`.
