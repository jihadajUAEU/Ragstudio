# Canonical Reference Units Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When document metadata declares structured reference units, Ragstudio should build one canonical answerable retrieval/vector/graph chunk per reference, while preserving the original parser blocks, pages, warnings, and recovered text as provenance.

**Architecture:** Add a metadata-driven canonicalization layer inside ingestion. `custom_json.reference_resolution` declares whether canonical units should be built. The splitter assembles reference headers plus body/continuation blocks into canonical chunks. Provenance-only source blocks are persisted for trace/debug, but are not treated as answerable retrieval evidence. The quality gate validates canonical chunks strictly and ignores provenance-only chunks as broken references.

**Tech Stack:** Python 3.12, FastAPI service layer, dataclasses/Pydantic schemas, SQLAlchemy async, Postgres JSON metadata, MinerU content-list normalization, existing `AdapterChunk`, `DomainMetadata`, `ReferenceSemantics`, and `DomainMetadataQualityGate`.

---

## Problem

The latest Bukhari repair reindex proved that reindexing alone is not enough.

Latest successful repair job:

- Job: `56f224a1-9b72-4919-b315-e79d4d39117a`
- Document: `fe0effdc-badb-4475-92dd-f7faa5d15f41`
- File: `hadith_bukhari.pdf`

Observed outcome:

| Metric | Previous Index | Latest Repair Index |
|---|---:|---:|
| Chunks | 6994 | 7473 |
| Unresolved references | 186 | 154 |
| Missing expected Arabic script | 534 | 1009 |
| Blocked references | 720 | 1163 |
| Script coverage | 92.1563% | 86.214% |
| Quarantined block warnings | 2074 | 0 |
| Recovered text warnings | 0 | 2553 |

The repair metadata was applied, and text-bearing blocks are now recovered instead of dropped. However, the splitter still emits header-only chunks such as `Book 1, Hadith 3` as answerable reference chunks. Those chunks have reference metadata but no Arabic body, so the quality gate correctly raises `reference_unit_missing_expected_script` and blocks vector/graph materialization.

Some following body chunks contain Arabic text but lack the reference metadata, so they become `reference_unit_unresolved`.

The missing behavior is canonical reference assembly:

```text
Reference header:
Book 1, Hadith 3

Following body blocks:
Arabic text...
English text...

Canonical output:
Book 1, Hadith 3
Arabic text...
English text...

Provenance:
original blocks, pages, parser warnings, block roles, hashes/previews
```

---

## Scope

This plan covers reindex-time canonicalization for structured-reference documents.

In scope:

- Metadata contract for reusable canonical reference units.
- General reference semantics, not Hadith-only logic.
- Splitter/reference assembly.
- Provenance metadata shape.
- Quality-gate behavior for canonical vs provenance-only chunks.
- Repair endpoint metadata promotion into stable keys.
- Backend tests and live Bukhari verification.
- Quran behavior using the same mechanism with verse-level units.

Out of scope:

- Training or fine-tuning an AI model.
- UI redesign.
- In-place migration of old chunks without reindexing.
- Relaxing warnings to hide missing Arabic.
- Hardcoded Bukhari-only or Quran-only chunking.

---

## Metadata Contract

Add stable metadata keys under `DomainMetadata.custom_json`. These keys should be reusable for Hadith, Quran, legal documents, manuals, and other structured-reference corpora.

### Hadith Example

```json
{
  "reference_schema": {
    "type": "book_hadith",
    "display": "Book {book}, Hadith {hadith}",
    "fields": {
      "book": "book_number",
      "hadith": "hadith_number"
    },
    "canonical_ref_template": "book:{book}:hadith:{hadith}"
  },
  "reference_resolution": {
    "enabled": true,
    "build_canonical_units": true,
    "carry_forward_body_blocks": true,
    "header_only_policy": "provenance_only",
    "continuation_policy": "until_next_reference",
    "max_page_gap": 2,
    "require_single_reference_per_answerable_chunk": true
  },
  "provenance": {
    "preserve_original_blocks": true,
    "block_preview_chars": 160,
    "store_text_hash": true
  },
  "chunking": {
    "unit": "hadith",
    "preserve_parallel_text": true,
    "merge_reference_header_with_body": true
  }
}
```

### Quran Example

```json
{
  "reference_schema": {
    "type": "quran_verse",
    "display": "{chapter}:{verse}",
    "fields": {
      "chapter": "chapter",
      "verse": "verse"
    },
    "canonical_ref_template": "{chapter}:{verse}"
  },
  "reference_resolution": {
    "enabled": true,
    "build_canonical_units": true,
    "carry_forward_body_blocks": true,
    "header_only_policy": "provenance_only",
    "continuation_policy": "until_next_reference",
    "max_page_gap": 1,
    "require_single_reference_per_answerable_chunk": true
  },
  "provenance": {
    "preserve_original_blocks": true,
    "block_preview_chars": 160,
    "store_text_hash": true
  },
  "chunking": {
    "unit": "verse",
    "preserve_parallel_text": true,
    "merge_reference_header_with_body": true
  }
}
```

### Activation Rule

Canonical assembly must activate only when all of these are true:

- `custom_json.reference_schema` exists.
- `custom_json.reference_resolution.enabled` is true.
- `custom_json.reference_resolution.build_canonical_units` is true.

Existing heuristic reference detection can still support search and metadata extraction, but it must not trigger canonical assembly unless the metadata contract opts in.

---

## Canonical Chunk Metadata

Canonical answerable chunks should preserve reference metadata and source provenance.

```json
{
  "reference_metadata": {
    "reference_type": "book_hadith",
    "references": ["book:1:hadith:3"],
    "display_reference": "Book 1, Hadith 3",
    "book_start": 1,
    "book_end": 1,
    "hadith_start": 3,
    "hadith_end": 3,
    "canonical_unit": true
  },
  "canonical_reference_unit": {
    "unit_type": "hadith",
    "reference": "book:1:hadith:3",
    "answerable": true,
    "assembly_strategy": "structured_reference_metadata",
    "body_status": "assembled"
  },
  "source_location": {
    "artifact": "source_42fe9a64/source/auto/source.md",
    "page_start": 4,
    "page_end": 5
  },
  "provenance": {
    "source": "mineru_content_list",
    "original_chunk_refs": ["parent:0:block:12", "parent:0:block:13"],
    "blocks": [
      {
        "role": "reference_header",
        "page_start": 4,
        "page_end": 4,
        "block_type": "heading",
        "text_hash": "sha256:...",
        "preview": "Book 1, Hadith 3"
      },
      {
        "role": "body",
        "page_start": 4,
        "page_end": 5,
        "block_type": "paragraph",
        "parser_warning_codes": ["recovered_text_from_disallowed_block"]
      }
    ]
  }
}
```

Header-only or unattachable source chunks should be provenance-only:

```json
{
  "canonical_reference_unit": {
    "answerable": false,
    "body_status": "header_only",
    "reference": "book:1:hadith:3"
  },
  "parser_metadata": {
    "provenance_only": true
  }
}
```

Use `content_type = "reference_provenance"` for persisted provenance-only chunks.

### Page Number Preservation

Ragstudio already persists PDF extraction page numbers on chunks through
`source_location.page_start` and `source_location.page_end`. Reference metadata
also carries `page_start` and `page_end` for reference-bearing chunks, and parser
warnings can carry a single `page`.

Canonical reference assembly must preserve page numbers at two levels:

1. **Canonical chunk range:** `source_location.page_start` is the minimum source
   page of the assembled reference unit and `source_location.page_end` is the
   maximum source page.
2. **Provenance block range:** every original header/body/continuation block in
   `provenance.blocks[]` stores its own `page_start` and `page_end`.

If a canonical unit spans pages 2-3, the canonical chunk should expose
`page_start = 2` and `page_end = 3`, while provenance should show which source
blocks came from page 2 versus page 3.

These are PDF extraction page numbers, not necessarily printed book page numbers
visible inside the scanned page.

---

## Implementation Tasks

### Task 1: Extend Reference Metadata Semantics

**Files:**

- Modify: `backend/src/ragstudio/services/reference_metadata.py`
- Modify: `backend/src/ragstudio/services/metadata_json_schema.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_service.py`
- Modify: `backend/tests/test_reference_metadata.py`
- Modify: `backend/tests/test_domain_metadata.py`

- [ ] Add reference-resolution fields to `ReferenceSemantics`:
  - `canonical_units_enabled`
  - `canonical_ref_template`
  - `header_only_policy`
  - `continuation_policy`
  - `max_page_gap`
  - `require_single_reference_per_answerable_chunk`
- [ ] Parse `custom_json.reference_resolution` with safe defaults.
- [ ] Add generic canonical reference rendering from named regex groups.
- [ ] Preserve existing Quran and Hadith reference parsing behavior.
- [ ] Update built-in Hadith and Quran domain profiles to declare stable `reference_resolution` and `provenance` keys.
- [ ] Validate the new metadata keys in `metadata_json_schema.py`.

**Verification:**

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_reference_metadata.py \
  backend/tests/test_domain_metadata.py \
  -q
```

### Task 2: Add Canonical Reference Unit Assembler

**Files:**

- Create: `backend/src/ragstudio/services/reference_unit_assembler.py`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Modify: `backend/tests/test_chunk_splitter.py`

- [ ] Introduce an ordered block model for canonical assembly:
  - text
  - page start/end
  - block type
  - parser warning codes
  - role: `reference_header`, `body`, `continuation`, `front_matter`, `noise`
  - source block ref
- [ ] Build this ordered block list from MinerU normalized content-list blocks.
- [ ] Detect reference headers using `ReferenceSemantics`.
- [ ] Accumulate body and continuation blocks until the next reference header.
- [ ] Stop accumulation across:
  - new reference
  - book/chapter boundary
  - page gap greater than `reference_resolution.max_page_gap`
  - configured front matter / non-reference boundary
- [ ] Emit one canonical `AdapterChunk` per assembled reference.
- [ ] Set canonical chunk `source_location.page_start` and `source_location.page_end` from the min/max pages of attached source blocks.
- [ ] Attach header/body/original warning provenance to the canonical chunk.
- [ ] Preserve per-block `page_start` and `page_end` inside `provenance.blocks[]`.
- [ ] Mark unattached header-only chunks as `reference_provenance`, not answerable chunks.
- [ ] Keep the existing generic splitter path for documents without canonical assembly metadata.

**Verification:**

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_chunk_splitter.py \
  -q
```

### Task 3: Update Quality Gate For Canonical And Provenance Chunks

**Files:**

- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
- Modify: `backend/tests/test_domain_metadata_quality_gate.py`
- Modify: `backend/tests/test_index_quality_gate.py`

- [ ] Treat `content_type = "reference_provenance"` and `parser_metadata.provenance_only = true` as persisted but non-answerable.
- [ ] Do not count provenance-only chunks as `reference_unit_unresolved`.
- [ ] Assign provenance-only chunks this action policy:

```json
{
  "persist_chunk": true,
  "index_vector": false,
  "index_exact_arabic": false,
  "project_graph": false,
  "graph_confidence": "provenance_only",
  "quality_flags": ["provenance_only"]
}
```

- [ ] Keep canonical chunks strict.
- [ ] If a canonical answerable chunk has one reference but no required script, keep `reference_unit_missing_expected_script`.
- [ ] If metadata requires single-reference chunks, block canonical chunks that contain multiple unrelated references unless metadata explicitly allows ranges.
- [ ] Add tests proving header-only chunks stop inflating unresolved/missing-script counts.
- [ ] Add tests proving genuine missing Arabic in a canonical chunk still warns and blocks materialization.

**Verification:**

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_domain_metadata_quality_gate.py \
  backend/tests/test_index_quality_gate.py \
  -q
```

### Task 4: Make Repair Plans Write Durable Metadata Keys

**Files:**

- Modify: `backend/src/ragstudio/services/job_quality_warning_service.py`
- Modify: `backend/tests/test_job_quality_warnings.py`

- [ ] Keep `custom_json.repair` and `custom_json.repair_plan` as audit/history only.
- [ ] When warning repair detects structured reference split failures, write durable metadata under:
  - `custom_json.reference_resolution`
  - `custom_json.chunking`
  - `custom_json.parser_normalization`
  - `custom_json.provenance`
- [ ] Include `build_canonical_units = true` in repair reindex options when structured reference metadata exists.
- [ ] Make AI repair suggestion advisory only; deterministic durable metadata must still be generated if the model fails.
- [ ] Add tests proving the queued reindex options contain stable canonicalization keys outside `repair`.

**Verification:**

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_job_quality_warnings.py \
  -q
```

### Task 5: Persistence, Search, And Graph Guard Checks

**Files:**

- Modify if needed: `backend/src/ragstudio/services/chunk_persistence_service.py`
- Modify if needed: `backend/src/ragstudio/services/mineru_relationship_builder.py`
- Modify if needed: `backend/src/ragstudio/services/graph_materialization_service.py`
- Modify: `backend/tests/test_chunk_persistence_service.py`
- Modify: `backend/tests/test_mineru_relationship_builder.py`
- Modify: `backend/tests/test_graph_materialization_service.py`
- Modify or add: Arabic/hybrid search tests.

- [ ] Assert canonical chunks persist Arabic search fields when text contains Arabic.
- [ ] Assert canonical chunks persist the full `source_location` page range for multi-page reference units.
- [ ] Assert provenance blocks retain their original per-block page numbers.
- [ ] Assert provenance-only chunks persist but are not vectorized.
- [ ] Assert provenance-only chunks do not project into graph as hadith/verse nodes.
- [ ] Assert canonical chunks with passing quality can graph-project from `reference_metadata`.
- [ ] Assert retrieval for an exact reference returns the canonical chunk, not the header-only provenance chunk.

**Verification:**

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_chunk_persistence_service.py \
  backend/tests/test_mineru_relationship_builder.py \
  backend/tests/test_graph_materialization_service.py \
  -q
```

### Task 6: Live Bukhari Verification

**Files:** No production files expected.

- [ ] Reindex document `fe0effdc-badb-4475-92dd-f7faa5d15f41` after implementation.
- [ ] Compare against latest baseline:

```bash
curl -s http://127.0.0.1:8000/api/jobs/56f224a1-9b72-4919-b315-e79d4d39117a/quality-warnings \
  | jq '.parser_quality.warning_counts, .index_quality_report.summary'
```

- [ ] Query chunk search for `Book 1, Hadith 3`.
- [ ] Verify top result is one canonical answerable chunk containing the reference header plus body text.
- [ ] Verify the canonical result exposes a correct `source_location.page_start` / `page_end` range.
- [ ] Verify provenance lists source block page ranges for the assembled header/body blocks.
- [ ] Verify header-only chunks are either absent from normal retrieval or marked `reference_provenance`.
- [ ] Query Arabic text known to exist in Bukhari and verify `arabic_exact` / `arabic_token` signals still work.
- [ ] Confirm warnings after reindex are sample-audited.

Expected result:

| Metric | Latest Repair Baseline | Target |
|---|---:|---:|
| Unresolved references | 154 | 0 for answerable body chunks |
| Missing expected Arabic script | 1009 | only genuine OCR/source misses |
| Blocked references | 1163 | 0 caused by header/body split |
| Script coverage | 86.214% | >= 92.1563%, target >= 98% |
| Header-only top evidence | present | absent |

---

## Rollout Notes

1. Do not promote this to a reusable preset until Bukhari verification improves the quality metrics.
2. Once verified, promote only stable metadata keys:
   - `reference_schema`
   - `reference_resolution`
   - `chunking`
   - `parser_normalization`
   - `provenance`
   - `graph_materialization` if needed
3. Do not promote:
   - `repair_plan`
   - `ai_suggestion`
   - `source_job_id`
   - `document_id`
   - sample warning rows

---

## Generalization Rules

This should work broadly for structured-reference documents, but not universally for all PDFs.

| Domain | Canonical unit |
|---|---|
| Quran | chapter:verse |
| Hadith | book:hadith |
| Legal | section/subsection |
| Manuals | heading/procedure |
| Academic papers | section plus paragraph/table/figure when metadata opts in |

For generic PDFs, keep the existing splitter path.

For structured-reference PDFs, the invariant is:

```text
one reference -> one canonical answerable chunk -> provenance points back to source blocks
```

---

## Risks And Guardrails

- Do not carry forward body text across a new reference.
- Do not cross book/chapter boundaries.
- Do not exceed `reference_resolution.max_page_gap`.
- Do not merge two references into one answerable chunk unless metadata explicitly allows ranges.
- Do not treat title/front matter as unresolved reference chunks.
- Do not delete parser warnings; preserve them in provenance.
- Do not index provenance-only chunks into vector search, exact Arabic search, or graph projection.
- Do not silently lower expected-script requirements to make warnings disappear.
- Remaining warnings are acceptable only when sample audit proves the canonical assembled unit truly lacks required text.

---

## Completion Criteria

- [ ] Metadata contract supports canonical reference units for Hadith and Quran examples.
- [ ] Splitter emits canonical chunks and provenance-only chunks correctly.
- [ ] Canonical chunks preserve aggregate page ranges and provenance blocks preserve original page ranges.
- [ ] Quality gate distinguishes canonical answerable chunks from provenance-only chunks.
- [ ] Repair endpoint writes stable canonicalization keys outside audit-only `repair`.
- [ ] Unit tests pass for reference semantics, splitter, quality gate, and warning repair.
- [ ] Live Bukhari reindex beats the old 92.1563% script coverage baseline or produces audited evidence that remaining misses are genuine source/OCR loss.
- [ ] `Book 1, Hadith 3` retrieves a canonical chunk with body text, not a header-only chunk.
- [ ] Quran-style metadata produces verse-level canonical chunks.
