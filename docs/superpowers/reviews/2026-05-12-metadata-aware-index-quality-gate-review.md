# Metadata-Aware Index Quality Gate Design Review

Reviewed: 2026-05-12T03:32:10Z
Scope: `docs/superpowers/specs/2026-05-12-metadata-aware-index-quality-gate.md`
Review type: design / architecture review
Status: issues_found

## Summary

The design identifies the right class of failure: document-level Arabic coverage is not enough when `DomainMetadata` promises verse-level Arabic plus translation. However, the spec is not yet sufficient to prevent the Quran/Tafseer `[19:13]` failure end to end. The weak points are the reference-unit data contract, where quality reports are persisted, and how vector/graph materialization consumes quality decisions.

## Findings

### CR-01: BLOCKER - Reference-unit validation is still chunk-shaped and can miss the exact per-verse loss

**Location:** `docs/superpowers/specs/2026-05-12-metadata-aware-index-quality-gate.md`, "Reference Unit Quality Gate" and "Chunking Strategy" sections, lines 97-115 and 154-189.

**Issue:** The spec says the gate runs "for each chunk" and uses `reference_metadata`, but it does not require a canonical per-reference text span or enforce exactly one metadata reference unit per Quran verse chunk. In the current architecture, `reference_metadata` is a list/range of references, not a per-reference text map, and relationship/chunking code can still produce chunks that contain multiple references. That means Arabic in one verse can mask Arabic loss in another verse inside the same chunk. If the parser loses the reference label too, the proposed gate has no `reference_metadata` anchor and can skip the failing unit entirely.

**Recommendation:** Define a hard contract for metadata-rich domains:

- For `custom_json.chunking.unit=verse`, persisted canonical chunks must either contain exactly one reference unit or include `quality.by_reference` records with `reference`, `text_span`, `arabic_token_count`, `latin_token_count`, `parser_warning_codes`, and `source_location`.
- Add a `reference_unit_unresolved` finding for chunks in a structured domain that cannot derive `reference_metadata`.
- Fail or quarantine before persistence/materialization when reference units cannot be isolated.
- Add a regression where `[19:12]` has Arabic and `[19:13]` does not inside one chunk; the gate must fail or quarantine only `[19:13]`.

### CR-02: BLOCKER - Zero-result retrieval diagnostics require a persisted reference-quality report, not only chunk warnings

**Location:** Spec "Retrieval Orchestrator Impact" and "Implementation Plan", lines 206-229 and 271-276.

**Issue:** The spec expects a zero-result Arabic query such as `حنانا` to report missing expected-script coverage for `[19:13]`. That cannot be implemented reliably from candidate-level warnings alone: if the corrupted reference is skipped/quarantined or fails lexical retrieval, there may be no candidate to carry `extraction_quality.parser_warnings`. The current retrieval shape annotates parser warnings only after candidates exist; it does not describe a document/reference-level quality lookup for empty candidate sets.

**Recommendation:** Add a persisted `IndexQualityReport` or equivalent keyed by `document_id`, `runtime_profile_id` / `index_record_id`, and `quality_report_version`. It should include per-reference rows or JSON entries:

```json
{
  "reference": "19:13",
  "expected_scripts": ["arabic", "latin"],
  "observed_scripts": ["latin"],
  "status": "missing_expected_script",
  "action": "block_exact_arabic_retrieval"
}
```

Retrieval should query this report by selected `document_ids`, query script, and reference hints, then add a `quality_diagnostics` trace even when `metadata_candidates`, `native_candidates`, and `graph_candidates` are all empty.

### CR-03: BLOCKER - Vector and graph materialization are not given an enforceable quality policy contract

**Location:** Spec "Vector And Graph Impact" and "Implementation Plan", lines 191-204 and 269-276.

**Issue:** The spec says the storage architecture does not need to change and that corrupt units can be embedded with flags or skipped, but it does not define the policy object that vector/runtime indexing and graph projection must consume. In the current runtime path, pre-parsed chunks are handed to native indexing, and the native content-list payload keeps only `id`, `type`, `text`, and page data. That strips quality metadata from the vector materialization path. Graph projection similarly reads `relationship_metadata` from all persisted chunks unless a specific quality-aware filter is added.

**Recommendation:** Make `QualityActionPolicy` produce a concrete per-chunk/per-reference decision consumed before every materialization branch:

- `persist_chunk: true|false`
- `index_vector: true|false`
- `index_exact_arabic: true|false`
- `project_graph: true|false`
- `graph_confidence: high|degraded|blocked`
- `quality_flags: [...]`

`IndexLifecycleService` should apply this before `persist_studio_chunks`, native `index_preparsed_chunks`, and graph projection record creation. If a corrupted unit is retained for inspection, native vector payloads and graph nodes must carry the quality flags; if not retained, it must be excluded from those materialization inputs.

### WR-01: WARNING - Sentinel and strict-reference policy inputs are undefined

**Location:** Spec "Action Policy", lines 135-152.

**Issue:** The policy depends on "configured sentinel references" and "exact reference selected by the user during upload validation", but the spec does not define where those inputs live or how they reach the indexing job. Current index options are essentially parser mode plus `DomainMetadata`; evaluation sets are separate artifacts.

**Recommendation:** Add a `quality_policy` input to `IndexDocumentIn` or `DomainMetadata.custom_json`, with fields such as `sentinel_references`, `required_references`, `min_reference_script_coverage`, and `strict_missing_script_action`. For the Quran regression, explicitly configure `[19:13]` as a sentinel or state that non-sentinel missing Arabic is allowed only as `ready_with_warnings` plus quarantine.

### WR-02: WARNING - DomainMetadata normalization is underspecified and can drift from existing profiles

**Location:** Spec "Metadata Contract" and "Implementation Plan", lines 24-39 and 269-277.

**Issue:** The spec examples use values like `mixed`, `arabic`, `latin`, and `surah_number:verse_number`, while the existing Quran sample profile uses values such as `arabic_english`, `arabic_latin`, and `reference_schema.reference_regex`. Without a normalization contract, the quality profile resolver may depend on incidental tags rather than the intended fields, and semantic reference patterns can be misread as regular expressions.

**Recommendation:** Specify accepted aliases and validation rules:

- Normalize `mixed`, `arabic_english`, and `arabic_latin` into expected scripts `arabic` and `latin`.
- Distinguish semantic `reference_pattern` values from executable regex values.
- Accept or migrate `reference_schema.reference_regex`, `pattern`, and `regex` into one canonical field.
- Emit metadata validation warnings when profile fields conflict or are unrecognized.

### WR-03: WARNING - Parser warning provenance is not precise enough for reference-level decisions

**Location:** Spec "Architecture" and "Reference Unit Quality Gate", lines 89-95 and 101-115.

**Issue:** The spec treats parser normalization warnings as inputs, but does not require them to be tied to a reference, content-list block, artifact, page, and span. Page-level or chunk-level warnings are not enough for Quran/Tafseer: one page can contain many verses, and a math-artifact warning on the page should not automatically taint every verse or miss the specific damaged verse.

**Recommendation:** Require parser warnings to persist with `artifact_ref`, `content_list_ref`, `block_index` or parser block id, page, recovered source, affected text span, and resolved reference when available. The reference quality gate should merge warnings into the same per-reference quality report from CR-02.

### WR-04: WARNING - Migration and backward compatibility are missing

**Location:** Spec "Implementation Plan" and "Acceptance Criteria", lines 269-286.

**Issue:** Existing indexed documents, vector entries, and graph projections will not have the new per-reference quality report. Without a migration or reindex policy, the observed Quran/Tafseer upload can continue to look healthy after the code ships, and retrieval cannot distinguish "quality passed" from "quality was never evaluated."

**Recommendation:** Add a migration plan:

- Add `quality_report_version`.
- Mark legacy indexes as `quality_unknown` until reindexed or backfilled.
- Backfill best-effort reports from existing `chunks.metadata_json` and `extraction_quality`.
- Mark graph/vector materialization stale when the quality report is missing or obsolete.
- Have retrieval traces say `quality_status=unknown` instead of silently treating old indexes as healthy.

### WR-05: WARNING - Evaluation plan misses the materialization and no-candidate retrieval cases

**Location:** Spec "Evaluation Plan", lines 231-267.

**Issue:** The listed tests cover basic gate emissions, but not the paths that make the design enforceable: runtime vector payload filtering/flagging, graph projection suppression, multi-reference chunk masking, missing `reference_metadata`, and zero-candidate retrieval diagnostics from a persisted report.

**Recommendation:** Add tests for:

- Multi-reference chunk where only `[19:13]` lacks Arabic.
- Structured Quran chunk with no resolvable `reference_metadata`.
- Arabic zero-result query that still emits `quality_diagnostics` from the persisted report.
- Native `index_preparsed_chunks` excludes or flags quarantined references.
- Graph materialization does not create high-confidence relationships for quarantined references.
- Legacy indexed documents return `quality_status=unknown`.

