# Quality Gate Warning Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every parser and modal quality warning produced during chunking visible to the final materialization gate, with user layout policy overrides applied before chunking decisions.

**Architecture:** Keep `DomainMetadataQualityGate` as the canonical warning storage and materialization policy owner. `ChunkSplitter` should generate and classify chunk warnings, but it should merge them only through `DomainMetadataQualityGate.merge_parser_warnings()` so all downstream readers use `metadata["extraction_quality"]["parser_warnings"]`. Modal validation should mutate chunk metadata before parser quality summaries and action policies are computed.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, Ragstudio backend services under `backend/src/ragstudio/services`.

---

## Verification Notes

Confirmed by code inspection:

- `backend/src/ragstudio/services/chunk_splitter.py:1008` currently calls the shared warning utility directly, which writes `metadata["parser_warnings"]`.
- `backend/src/ragstudio/services/domain_metadata_quality_gate.py:582` reads warnings from `chunk.extraction_quality` or `chunk.metadata["extraction_quality"]["parser_warnings"]`.
- `backend/src/ragstudio/services/domain_metadata_quality_gate.py:1387` returns modal warnings but does not merge them into the chunk metadata.
- `backend/src/ragstudio/services/domain_metadata_quality_gate.py:228` applies the intelligent gate before modal validation, so modal warnings cannot influence `_apply_parser_quality_action_policy()`.
- `backend/src/ragstudio/services/chunk_splitter.py:86` loops over every input chunk and calls `_split_chunk()`, while `_split_chunk()` calls `_chunks_from_content_list()` at `backend/src/ragstudio/services/chunk_splitter.py:177`. `_chunks_from_content_list()` reads and normalizes the full referenced content list at `backend/src/ragstudio/services/chunk_splitter.py:213`, so multiple parser chunks pointing at the same `content_list_ref` can reprocess the same full document repeatedly.
- `backend/src/ragstudio/services/index_lifecycle_service.py:142` calls `ModalPreprocessor().preprocess()`, and `backend/src/ragstudio/services/modal_preprocessor.py:50` already delegates to `StudioModalRouter().route()`. The router is not fully disconnected, but the lifecycle dependency hides the real routing boundary behind an older wrapper name and makes router behavior hard to inject or test directly.
- `backend/src/ragstudio/services/parser_normalization.py:820` stitches page-boundary paragraphs with `_should_stitch_page_boundary()`, and `backend/src/ragstudio/services/parser_normalization.py:1192` relies on fast punctuation/header/case/script heuristics. This is a valid architectural hardening target, but not yet proven as a correctness bug for a specific corpus.
- `backend/src/ragstudio/services/chunk_persistence_service.py:79` records `chunk_ids` in input order, then `backend/src/ragstudio/services/chunk_persistence_service.py:82` refreshes with `select(Chunk).where(Chunk.id.in_(chunk_ids))` and no ordering. SQL does not guarantee `IN` result order, so returned `ChunkOut` values can lose the adapter chunk sequence even if inserts were staged in order.

Confirmed by runtime probes:

- `ChunkSplitter.split()` on a Quran-style English-only reference chunk writes `parser_warnings` at metadata root and leaves `extraction_quality` absent.
- Modal table validation returns `table_missing_structure` in the report while leaving `chunk.metadata` unchanged.

Existing test issue:

- `backend/tests/test_chunk_splitter.py::test_chunk_splitter_dedupes_existing_quality_gate_warning` is currently synchronous even though `ChunkSplitter.split()` is async. Running it directly fails with `TypeError: 'coroutine' object is not subscriptable`, so this plan includes converting the affected splitter regression tests to async before relying on them.

## File Structure

- Modify `backend/src/ragstudio/services/chunk_splitter.py`: use the canonical domain gate merge method and classify raw `ChunkQualityGate` warnings before both merging and chunk-preservation decisions.
- Modify `backend/src/ragstudio/services/chunk_splitter.py`: group content-list processing by resolved JSON reference so a document-level `source_content_list.json` is parsed and normalized once per splitter run.
- Modify `backend/src/ragstudio/services/domain_metadata_quality_gate.py`: persist modal validation warnings into chunk extraction quality and run modal validation before parser warning classification, policy application, and summary creation.
- Modify `backend/src/ragstudio/services/index_lifecycle_service.py`: make the `StudioModalRouter` boundary explicit in the lifecycle path, either by injecting a router-backed preprocessing dependency or by moving the small adapter logic out of the legacy `ModalPreprocessor` wrapper.
- Modify `backend/src/ragstudio/services/parser_normalization.py`: add a scored, explainable page-stitch decision object that can consume domain hints and emit metadata about why a boundary was or was not stitched.
- Modify `backend/src/ragstudio/services/chunk_persistence_service.py`: restore bulk-refreshed chunks to the original `chunk_ids` order before returning `ChunkOut` values.
- Modify `backend/tests/test_chunk_splitter.py`: convert affected splitter tests to async and add regressions for nested warning propagation and intelligent-gate-aware enrichment.
- Modify `backend/tests/test_domain_metadata_quality_gate.py`: add regressions proving modal warnings are persisted and can block materialization policy.
- Modify `backend/tests/test_index_lifecycle_service.py`: add direct regression coverage that lifecycle indexing uses the router-backed modal path.
- Modify `backend/tests/test_parser_normalization.py`: add page-boundary stitching regressions for positive, negative, and domain-hinted decisions.
- Modify `backend/tests/test_chunk_persistence_service.py`: add a regression proving `persist()` returns chunks in adapter input order even when the database returns refreshed rows out of order.

---

### Task 1: Fix Chunk Splitter Parser Warning Storage

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_splitter.py:11-17`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py:886-914`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py:967-1014`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write the failing nested warning propagation test**

Add this import near the existing imports in `backend/tests/test_chunk_splitter.py`:

```python
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
```

Replace `test_chunk_splitter_dedupes_existing_quality_gate_warning` with this async version:

```python
@pytest.mark.asyncio
async def test_chunk_splitter_dedupes_existing_quality_gate_warning():
    warning = {
        "code": "reference_unit_missing_expected_script",
        "message": (
            "Reference-bearing chunk is expected to contain Arabic script, "
            "but no Arabic letters were detected."
        ),
        "expected_script": "arabic",
    }
    chunk = AdapterChunk(
        text="[1:1] English translation only.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={
            "parser_metadata": {"backend": "mineru", "chunk_index": 0},
            "extraction_quality": {"parser_warnings": [warning]},
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    warnings = parser_warnings(split[0])
    assert warnings == [warning]
    assert "parser_warnings" not in split[0].metadata
```

Add this new test next to it:

```python
@pytest.mark.asyncio
async def test_chunk_splitter_writes_quality_gate_warnings_to_extraction_quality():
    chunk = AdapterChunk(
        text="[1:1] English translation only.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    warnings = parser_warnings(split[0])
    assert [warning["code"] for warning in warnings] == [
        "reference_unit_missing_expected_script"
    ]
    assert "parser_warnings" not in split[0].metadata
    assert DomainMetadataQualityGate().parser_warnings_for_chunk(split[0]) == warnings
```

- [ ] **Step 2: Run the focused splitter tests and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_dedupes_existing_quality_gate_warning backend/tests/test_chunk_splitter.py::test_chunk_splitter_writes_quality_gate_warnings_to_extraction_quality -q
```

Expected: at least the new nested warning test fails because `ChunkSplitter._merge_parser_warnings()` still writes root-level `metadata["parser_warnings"]`.

- [ ] **Step 3: Route splitter warning merges through the canonical domain gate**

In `backend/src/ragstudio/services/chunk_splitter.py`, replace the shared warning utility import:

```python
from ragstudio.services.parser_warning_utils import (
    merge_parser_warnings as _shared_merge_parser_warnings,
)
```

with:

```python
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.parser_quality_intelligent_gate import ParserQualityIntelligentGate
```

Then replace `_merge_parser_warnings()` with:

```python
    def _merge_parser_warnings(
        self,
        metadata: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> None:
        DomainMetadataQualityGate.merge_parser_warnings(metadata, warnings)
```

- [ ] **Step 4: Run the focused splitter tests and verify pass**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_dedupes_existing_quality_gate_warning backend/tests/test_chunk_splitter.py::test_chunk_splitter_writes_quality_gate_warnings_to_extraction_quality -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit the splitter storage fix**

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_splitter.py
git commit -m "fix: store splitter warnings in extraction quality"
```

---

### Task 2: Apply Intelligent Parser Gate During Chunking Decisions

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_splitter.py:886-1014`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write the failing intelligent-gate enrichment test**

Add this test to `backend/tests/test_chunk_splitter.py` near the quality warning tests:

```python
@pytest.mark.asyncio
async def test_chunk_splitter_does_not_enrich_unchanged_piece_for_info_only_warning():
    chunk = AdapterChunk(
        text="Verse 18:30 Indeed, those who have believed.",
        source_location={"page_start": 809, "page_end": 809},
        metadata={
            "parser_metadata": {"backend": "mineru", "chunk_index": 0},
            "extraction_quality": {
                "parser_warnings": [
                    {
                        "code": "recovered_text_from_misclassified_block",
                        "block_type": "equation",
                        "message": "Used parser-provided recovered text.",
                    }
                ]
            },
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=tafseer_cross_reference_metadata(),
        parser_mode="mineru_strict",
    )

    assert split == [chunk]
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_does_not_enrich_unchanged_piece_for_info_only_warning -q
```

Expected: the test fails because `_should_enrich_unchanged()` treats any raw warning as enrichment-worthy before policy classification suppresses info-only accepted recoveries.

- [ ] **Step 3: Add classified warning helpers to `ChunkSplitter`**

Add these helper methods below `_should_enrich_unchanged()` in `backend/src/ragstudio/services/chunk_splitter.py`:

```python
    def _classified_quality_warnings(
        self,
        text: str,
        metadata: dict[str, Any],
        *,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> list[dict[str, Any]]:
        warnings = ChunkQualityGate(expected_profile, domain_metadata).warnings_for(
            text,
            metadata,
        )
        return ParserQualityIntelligentGate().classify_warnings(
            warnings,
            domain_metadata=domain_metadata,
        )

    def _warnings_require_chunk_enrichment(
        self,
        warnings: list[dict[str, Any]],
    ) -> bool:
        return any(
            not bool(warning.get("suppressed_from_counts"))
            for warning in warnings
        )
```

- [ ] **Step 4: Use classified warnings before preserving or enriching pieces**

In `_with_split_metadata()`, replace:

```python
            self._merge_parser_warnings(
                metadata,
                ChunkQualityGate(expected_profile, domain_metadata).warnings_for(
                    piece.text,
                    metadata,
                ),
            )
```

with:

```python
            self._merge_parser_warnings(
                metadata,
                self._classified_quality_warnings(
                    piece.text,
                    metadata,
                    expected_profile=expected_profile,
                    domain_metadata=domain_metadata,
                ),
            )
```

In `_should_enrich_unchanged()`, replace:

```python
        if ChunkQualityGate(expected_profile, domain_metadata).warnings_for(
            piece.text,
            piece.metadata,
        ):
            return True
```

with:

```python
        warnings = self._classified_quality_warnings(
            piece.text,
            piece.metadata,
            expected_profile=expected_profile,
            domain_metadata=domain_metadata,
        )
        if self._warnings_require_chunk_enrichment(warnings):
            return True
```

- [ ] **Step 5: Run focused splitter tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_does_not_enrich_unchanged_piece_for_info_only_warning backend/tests/test_chunk_splitter.py::test_chunk_splitter_writes_quality_gate_warnings_to_extraction_quality -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit the intelligent gate chunking fix**

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_splitter.py
git commit -m "fix: classify parser warnings during chunking"
```

---

### Task 3: Persist Modal Validation Warnings Before Policy Evaluation

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py:191-239`
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py:1387-1424`
- Test: `backend/tests/test_domain_metadata_quality_gate.py`

- [ ] **Step 1: Write failing modal persistence and policy tests**

Add these tests to `backend/tests/test_domain_metadata_quality_gate.py` near the parser quality policy tests:

```python
def test_domain_quality_gate_persists_modal_table_warning():
    chunks = [
        AdapterChunk(
            text=" ",
            source_location={"page": 1},
            metadata={"modality": "table", "structured_data": {}},
        )
    ]

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=DomainMetadata(domain="generic", language="english"),
    )

    warnings = chunks[0].metadata["extraction_quality"]["parser_warnings"]
    policy = chunks[0].metadata["quality_action_policy"]
    assert report["status"] == "passed_with_warnings"
    assert report["modal_validation"] == warnings
    assert warnings[0]["code"] == "table_missing_structure"
    assert warnings[0]["severity"] == "block"
    assert warnings[0]["quality_gate_action"] == "block"
    assert policy["index_vector"] is False
    assert policy["project_graph"] is False
    assert "parser_quality_block:table_missing_structure" in policy["quality_flags"]


def test_domain_quality_gate_persists_modal_image_warning():
    chunks = [
        AdapterChunk(
            text=" ",
            source_location={"page": 1},
            metadata={"modality": "image", "structured_data": {"caption": []}},
        )
    ]

    DomainMetadataQualityGate().validate_adapter_chunks(
        chunks,
        domain_metadata=DomainMetadata(domain="generic", language="english"),
    )

    warnings = chunks[0].metadata["extraction_quality"]["parser_warnings"]
    assert warnings[0]["code"] == "image_missing_description"
    assert warnings[0]["source"] == "modal_validation"
```

- [ ] **Step 2: Run the focused modal tests and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_persists_modal_table_warning backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_persists_modal_image_warning -q
```

Expected: tests fail because `_validate_modal_chunks()` currently returns warnings without mutating chunk metadata.

- [ ] **Step 3: Move modal validation before parser policy evaluation**

In `validate_adapter_chunks()`, replace the block:

```python
        self._apply_intelligent_parser_gate(chunks, domain_metadata=domain_metadata)
        self._apply_parser_quality_action_policy(chunks)
        quality_summary = self.parser_quality_summary(chunks)
        status = "passed_with_warnings" if quality_summary["warning_counts"] else "passed"

        # Modal-aware validation: verify structure integrity per modality.
        modal_warnings = self._validate_modal_chunks(chunks)
```

with:

```python
        modal_warnings = self._validate_modal_chunks(chunks)
        self._apply_intelligent_parser_gate(chunks, domain_metadata=domain_metadata)
        self._apply_parser_quality_action_policy(chunks)
        quality_summary = self.parser_quality_summary(chunks)
        status = "passed_with_warnings" if quality_summary["warning_counts"] else "passed"
```

- [ ] **Step 4: Merge modal warnings into chunk extraction quality**

Replace `_validate_modal_chunks()` with:

```python
    def _validate_modal_chunks(
        self, chunks: list[AdapterChunk]
    ) -> list[dict[str, Any]]:
        """Validate modality-specific structural integrity."""
        warnings: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            chunk_warnings: list[dict[str, Any]] = []
            modality = chunk.metadata.get("modality", "text")
            if modality == "table":
                structured = chunk.metadata.get("structured_data", {})
                if not structured.get("markdown") and not structured.get("raw_body"):
                    chunk_warnings.append({
                        "chunk_index": index,
                        "modality": "table",
                        "code": "table_missing_structure",
                        "message": "Table chunk has no structured body data.",
                        "severity": "block",
                        "quality_gate_action": "block",
                        "quality_gate_reason": "modal_validation.table_missing_structure",
                        "source": "modal_validation",
                    })
            elif modality == "image":
                structured = chunk.metadata.get("structured_data", {})
                caption = structured.get("caption", [])
                if not caption and not chunk.text.strip():
                    chunk_warnings.append({
                        "chunk_index": index,
                        "modality": "image",
                        "code": "image_missing_description",
                        "message": "Image chunk has no caption or description.",
                        "severity": "block",
                        "quality_gate_action": "block",
                        "quality_gate_reason": "modal_validation.image_missing_description",
                        "source": "modal_validation",
                    })
            elif modality == "equation":
                structured = chunk.metadata.get("structured_data", {})
                if not structured.get("latex"):
                    chunk_warnings.append({
                        "chunk_index": index,
                        "modality": "equation",
                        "code": "equation_missing_latex",
                        "message": "Equation chunk has no LaTeX content.",
                        "severity": "block",
                        "quality_gate_action": "block",
                        "quality_gate_reason": "modal_validation.equation_missing_latex",
                        "source": "modal_validation",
                    })

            if chunk_warnings:
                self.merge_parser_warnings(chunk.metadata, chunk_warnings)
                warnings.extend(chunk_warnings)

        if warnings:
            logger.info(
                "Modal validation: %d warning(s) across %d chunks",
                len(warnings), len(chunks),
            )
        return warnings
```

- [ ] **Step 5: Run focused modal tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_persists_modal_table_warning backend/tests/test_domain_metadata_quality_gate.py::test_domain_quality_gate_persists_modal_image_warning -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit the modal validation fix**

```bash
git add backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/tests/test_domain_metadata_quality_gate.py
git commit -m "fix: persist modal validation warnings"
```

---

### Task 4: Process Each Content List Once Per Splitter Run

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_splitter.py:86-145`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py:177-281`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write the failing duplicate content-list processing test**

Add this test to `backend/tests/test_chunk_splitter.py` near the other `source_content_list.json` splitter tests:

```python
@pytest.mark.asyncio
async def test_chunk_splitter_processes_shared_content_list_once(tmp_path, monkeypatch):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "First paragraph.", "page_idx": 0},
                {"type": "text", "text": "Second paragraph.", "page_idx": 0},
            ]
        ),
        encoding="utf-8",
    )
    parser_metadata = {
        "backend": "mineru",
        "artifact_extract_dir": str(tmp_path),
        "content_list_ref": "source_content_list.json",
    }
    chunks = [
        AdapterChunk(
            text=f"placeholder {index}",
            source_location={"artifact": "source.md"},
            metadata={"parser_metadata": parser_metadata},
        )
        for index in range(3)
    ]
    splitter = ChunkSplitter(max_words=1500)
    calls = 0
    original = splitter.content_normalizer.normalize_content_list

    async def counted_normalize(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(
        splitter.content_normalizer,
        "normalize_content_list",
        counted_normalize,
    )

    split = await splitter.split(
        chunks,
        domain_metadata=DomainMetadata(domain="general"),
        parser_mode="mineru_strict",
    )

    assert calls == 1
    assert [chunk.text for chunk in split] == ["First paragraph.\n\nSecond paragraph."]
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_processes_shared_content_list_once -q
```

Expected: FAIL with `calls == 3` or duplicate output chunks, proving the splitter reprocesses a shared document-level content list for every placeholder chunk.

- [ ] **Step 3: Add content-list key extraction**

Add this dataclass near `ContentListSplitResult` in `backend/src/ragstudio/services/chunk_splitter.py`:

```python
@dataclass(frozen=True)
class ContentListKey:
    root: Path
    content_ref: str
```

Add this helper below `_split_chunk()`:

```python
    def _content_list_key(self, chunk: AdapterChunk) -> ContentListKey | None:
        if chunk.metadata.get(MODAL_ROUTER_PROCESSED_FLAG) is True:
            return None
        parser_metadata = self._parser_metadata(chunk)
        extract_dir = parser_metadata.get("artifact_extract_dir")
        content_ref = parser_metadata.get("content_list_ref")
        if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
            return None
        if not extract_dir.strip() or not content_ref.strip():
            return None
        return ContentListKey(Path(extract_dir).resolve(), content_ref)
```

- [ ] **Step 4: Skip repeated handled content-list chunks**

In `split()`, add a processed-key set before the chunk loop:

```python
        processed_content_lists: set[ContentListKey] = set()
```

At the start of the loop, before calling `_split_chunk()`, add:

```python
            content_list_key = self._content_list_key(chunk)
            if content_list_key is not None and content_list_key in processed_content_lists:
                continue
```

Immediately after `_split_chunk()` returns, add:

```python
            if content_list_key is not None and pieces:
                processed_content_lists.add(content_list_key)
```

This keeps non-content-list chunks unchanged while ensuring one document-level content list produces one canonical piece set per splitter run.

- [ ] **Step 5: Run duplicate and existing content-list tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_processes_shared_content_list_once backend/tests/test_chunk_splitter.py::test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit the content-list de-duplication fix**

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_splitter.py
git commit -m "fix: process shared content lists once"
```

---

### Task 5: Make Modal Routing Explicit in Index Lifecycle

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py:22`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py:58-80`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py:140-146`
- Test: `backend/tests/test_index_lifecycle_service.py`

Note: this is an architectural cleanup, not a confirmed disconnected-router bug. Current production indexing already reaches `StudioModalRouter` through `ModalPreprocessor`, but the lifecycle dependency should expose the router-backed boundary directly so future multimodal behavior is not hidden behind a legacy wrapper.

- [ ] **Step 1: Write the router injection regression**

Add this helper class near other test fakes in `backend/tests/test_index_lifecycle_service.py`:

```python
class RecordingModalPreprocessor:
    def __init__(self) -> None:
        self.calls: list[list[AdapterChunk]] = []

    def preprocess(
        self,
        adapter_chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        self.calls.append(adapter_chunks)
        return [
            AdapterChunk(
                text="router table text",
                source_location={"artifact": "source_content_list.json", "page_start": 1, "page_end": 1},
                metadata={
                    "modal_router_processed": True,
                    "modality": "table",
                    "structured_data": {"markdown": "| A |"},
                    "parser_metadata": {
                        "artifact_extract_dir": adapter_chunks[0].metadata["parser_metadata"][
                            "artifact_extract_dir"
                        ],
                        "content_list_ref": "source_content_list.json",
                    },
                },
                runtime_source_id=adapter_chunks[0].runtime_source_id,
            )
        ]
```

Add this test next to `test_reindex_document_applies_modal_preprocessor`:

```python
@pytest.mark.asyncio
async def test_reindex_document_uses_injected_modal_preprocessor(session, app, tmp_path):
    artifact_path = tmp_path / "modal.pdf"
    artifact_path.write_bytes(b"%PDF-1.4\n")
    document = Document(
        id="doc-modal-injected",
        filename="modal.pdf",
        content_type="application/pdf",
        artifact_path=str(artifact_path),
        sha256="modal-injected",
        status=StageStatus.SUCCEEDED.value,
    )
    session.add_all(
        [
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                mineru_enabled=True,
                mineru_base_url="http://mineru.test",
            ),
            document,
        ]
    )
    await session.commit()

    parser_chunk = AdapterChunk(
        text="raw parser placeholder",
        source_location={"artifact": "source.md"},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
        runtime_source_id="runtime-modal",
    )
    modal_preprocessor = RecordingModalPreprocessor()
    runtime = PreparsedRuntime()

    result = await IndexLifecycleService(
        session,
        app.state.settings,
        runtime_factory=FakeFactory(runtime),
        health_service=FakeHealthService(),
        document_parser=FakeDocumentParser([parser_chunk]),
        modal_preprocessor=modal_preprocessor,
    ).reindex_document(
        document.id,
        options=IndexDocumentIn(domain_metadata=DomainMetadata(domain="general")),
    )

    assert result is not None
    assert len(modal_preprocessor.calls) == 1
    assert runtime.preparsed_chunks[0].metadata["modal_router_processed"] is True
    assert runtime.preparsed_chunks[0].metadata["modality"] == "table"
```

- [ ] **Step 2: Run the focused lifecycle test and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_index_lifecycle_service.py::test_reindex_document_uses_injected_modal_preprocessor -q
```

Expected: FAIL because `IndexLifecycleService.__init__()` does not accept `modal_preprocessor`.

- [ ] **Step 3: Inject the router-backed modal preprocessing boundary**

In `IndexLifecycleService.__init__()`, add a keyword parameter:

```python
        modal_preprocessor: Any | None = None,
```

Then assign it with the existing default:

```python
        self.modal_preprocessor = modal_preprocessor or ModalPreprocessor()
```

Replace:

```python
            normalized_chunks = ModalPreprocessor().preprocess(
                normalized_chunks,
                domain_metadata=options.domain_metadata,
            )
```

with:

```python
            normalized_chunks = self.modal_preprocessor.preprocess(
                normalized_chunks,
                domain_metadata=options.domain_metadata,
            )
```

- [ ] **Step 4: Run modal lifecycle tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_index_lifecycle_service.py::test_reindex_document_applies_modal_preprocessor backend/tests/test_index_lifecycle_service.py::test_reindex_document_uses_injected_modal_preprocessor -q
```

Expected: both tests pass. The first proves the current `StudioModalRouter` delegation still works through the default adapter; the second proves the lifecycle path has an explicit injectable multimodal boundary.

- [ ] **Step 5: Commit the modal lifecycle boundary cleanup**

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_index_lifecycle_service.py
git commit -m "refactor: expose modal preprocessing boundary"
```

---

### Task 6: Harden Page-Boundary Stitching Decisions

**Files:**
- Modify: `backend/src/ragstudio/services/parser_normalization.py:820-832`
- Modify: `backend/src/ragstudio/services/parser_normalization.py:1192-1265`
- Test: `backend/tests/test_parser_normalization.py`

This task keeps the fast heuristic path but makes the decision explainable and tunable by domain metadata. Do not introduce live LLM calls in normalization; vision recovery can provide text recovery before stitching, but page stitching must remain deterministic for tests and static fixtures.

- [ ] **Step 1: Write the domain-hinted stitching tests**

Add these tests to `backend/tests/test_parser_normalization.py` near existing page-boundary stitching tests:

```python
@pytest.mark.asyncio
async def test_normalizer_respects_domain_disabled_page_boundary_stitching():
    normalizer = MinerUContentNormalizer()
    content_list = [
        {"type": "text", "text": "This sentence continues", "page_idx": 0},
        {"type": "text", "text": "on the next page", "page_idx": 1},
    ]

    blocks = await normalizer.normalize_content_list(
        content_list,
        domain_metadata=DomainMetadata(
            custom_json={"page_boundary_stitching": {"enabled": False}}
        ),
        expected_profile=ExpectedContentProfile(),
    )

    assert [block.text for block in blocks] == [
        "This sentence continues",
        "on the next page",
    ]


@pytest.mark.asyncio
async def test_normalizer_records_page_boundary_stitch_reason():
    normalizer = MinerUContentNormalizer()
    content_list = [
        {"type": "text", "text": "This sentence continues", "page_idx": 0},
        {"type": "text", "text": "on the next page", "page_idx": 1},
    ]

    blocks = await normalizer.normalize_content_list(
        content_list,
        domain_metadata=DomainMetadata(),
        expected_profile=ExpectedContentProfile(),
    )

    assert len(blocks) == 1
    assert blocks[0].source_item["semantic_stitch"] == "page_boundary"
    assert blocks[0].source_item["stitch_decision"]["reason"] == "sentence_continuation"
```

- [ ] **Step 2: Run the focused parser normalization tests and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_parser_normalization.py::test_normalizer_respects_domain_disabled_page_boundary_stitching backend/tests/test_parser_normalization.py::test_normalizer_records_page_boundary_stitch_reason -q
```

Expected: FAIL because stitching cannot be disabled by metadata and stitched output does not include a structured decision reason.

- [ ] **Step 3: Add a stitch decision dataclass**

Add this dataclass near the other parser normalization dataclasses:

```python
@dataclass(frozen=True)
class PageStitchDecision:
    stitch: bool
    reason: str
```

- [ ] **Step 4: Thread domain metadata into stitching**

Change the `_stitch_page_boundary_paragraphs()` signature to:

```python
    def _stitch_page_boundary_paragraphs(
        self,
        normalized: list[NormalizedBlock],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[NormalizedBlock]:
```

At its call site, replace:

```python
            normalized = self._stitch_page_boundary_paragraphs(normalized)
```

with:

```python
            normalized = self._stitch_page_boundary_paragraphs(
                normalized,
                domain_metadata=domain_metadata,
            )
```

Replace the body condition with:

```python
            decision = _page_stitch_decision(
                stitched[-1],
                block,
                domain_metadata=domain_metadata,
            )
            if stitched and decision.stitch:
                stitched[-1] = _stitch_blocks_across_page_boundary(
                    stitched[-1],
                    block,
                    stitch_decision=decision,
                )
                continue
```

- [ ] **Step 5: Replace boolean stitching with an explainable decision**

Replace `_should_stitch_page_boundary()` with:

```python
def _page_stitch_decision(
    previous: NormalizedBlock,
    current: NormalizedBlock,
    *,
    domain_metadata: DomainMetadata,
) -> PageStitchDecision:
    policy = _dict_value(domain_metadata.custom_json, "page_boundary_stitching") or {}
    if policy.get("enabled") is False:
        return PageStitchDecision(False, "disabled_by_domain_policy")
    previous_page_end = _source_page_end(previous)
    current_page_start = _source_page_start(current)
    if previous_page_end is None or current_page_start is None:
        return PageStitchDecision(False, "missing_page_boundary")
    if current_page_start != previous_page_end + 1:
        return PageStitchDecision(False, "non_adjacent_pages")
    if previous.warnings or current.warnings or previous.recovery or current.recovery:
        return PageStitchDecision(False, "quality_or_recovery_present")
    if not _is_page_stitch_text_block(previous) or not _is_page_stitch_text_block(current):
        return PageStitchDecision(False, "non_text_block")
    if _ends_with_terminal_punctuation(previous.text):
        return PageStitchDecision(False, "previous_terminal_punctuation")
    if _looks_like_page_stitch_boundary(current.text):
        return PageStitchDecision(False, "current_starts_new_boundary")
    if _starts_like_sentence_continuation(previous.text, current.text):
        return PageStitchDecision(True, "sentence_continuation")
    return PageStitchDecision(False, "no_continuation_signal")
```

Change `_stitch_blocks_across_page_boundary()` to accept and store the decision:

```python
def _stitch_blocks_across_page_boundary(
    previous: NormalizedBlock,
    current: NormalizedBlock,
    *,
    stitch_decision: PageStitchDecision,
) -> NormalizedBlock:
```

Add this to the `source_item.update(...)` payload:

```python
            "stitch_decision": {
                "reason": stitch_decision.reason,
                "strategy": "deterministic_page_boundary",
            },
```

- [ ] **Step 6: Run parser normalization regressions**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_parser_normalization.py -q
```

Expected: all parser normalization tests pass.

- [ ] **Step 7: Commit the page stitching hardening**

```bash
git add backend/src/ragstudio/services/parser_normalization.py backend/tests/test_parser_normalization.py
git commit -m "refactor: explain page boundary stitching decisions"
```

---

### Task 7: Preserve Chunk Persistence Return Order

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_persistence_service.py:79-85`
- Test: `backend/tests/test_chunk_persistence_service.py`

- [ ] **Step 1: Write the persistence ordering regression**

Add this test to `backend/tests/test_chunk_persistence_service.py` near the other `persist()` tests:

```python
async def test_persist_returns_chunks_in_adapter_input_order(session):
    document = Document(
        id="doc-order",
        filename="order.pdf",
        content_type="application/pdf",
        artifact_path="/tmp/order.pdf",
        sha256="order",
        status="succeeded",
    )
    session.add(document)
    await session.commit()

    adapter_chunks = [
        AdapterChunk(
            text="first chunk",
            source_location={"page": 1},
            metadata={"parser_metadata": {"chunk_index": 0}},
        ),
        AdapterChunk(
            text="second chunk",
            source_location={"page": 2},
            metadata={"parser_metadata": {"chunk_index": 1}},
        ),
        AdapterChunk(
            text="third chunk",
            source_location={"page": 3},
            metadata={"parser_metadata": {"chunk_index": 2}},
        ),
    ]

    chunks = await ChunkPersistenceService(session).persist(
        document,
        adapter_chunks,
        IndexDocumentIn(domain_metadata=DomainMetadata()),
    )

    assert [chunk.text for chunk in chunks] == [
        "first chunk",
        "second chunk",
        "third chunk",
    ]
    assert [
        chunk.metadata_json["parser_metadata"]["chunk_index"]
        for chunk in chunks
    ] == [0, 1, 2]
```

- [ ] **Step 2: Strengthen the test against unordered refreshes**

If the regression passes before the implementation change because the current test database happens to return insertion order, add a direct helper-level test by extracting the ordering logic in Step 3 first, then test it with reversed rows:

```python
def test_order_chunks_by_ids_restores_bulk_refresh_order():
    first = SimpleNamespace(id="chunk-1", text="first")
    second = SimpleNamespace(id="chunk-2", text="second")
    third = SimpleNamespace(id="chunk-3", text="third")

    ordered = ChunkPersistenceService._order_chunks_by_ids(
        [third, first, second],
        ["chunk-1", "chunk-2", "chunk-3"],
    )

    assert [chunk.text for chunk in ordered] == ["first", "second", "third"]
```

Add `from types import SimpleNamespace` at the top of the test file if this helper test is needed.

- [ ] **Step 3: Add deterministic ordering after bulk refresh**

In `backend/src/ragstudio/services/chunk_persistence_service.py`, replace:

```python
            chunks = list(result.scalars().all())
```

with:

```python
            chunks = self._order_chunks_by_ids(
                list(result.scalars().all()),
                chunk_ids,
            )
```

Add this static helper below `persist()`:

```python
    @staticmethod
    def _order_chunks_by_ids(chunks: list[Chunk], chunk_ids: list[str]) -> list[Chunk]:
        by_id = {chunk.id: chunk for chunk in chunks}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]
```

- [ ] **Step 4: Run the focused persistence tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_persistence_service.py::test_persist_returns_chunks_in_adapter_input_order backend/tests/test_chunk_persistence_service.py::test_order_chunks_by_ids_restores_bulk_refresh_order -q
```

Expected: all included tests pass. If the helper test was not needed, omit its node id from the command.

- [ ] **Step 5: Commit the persistence ordering fix**

```bash
git add backend/src/ragstudio/services/chunk_persistence_service.py backend/tests/test_chunk_persistence_service.py
git commit -m "fix: preserve persisted chunk order"
```

---

### Task 8: Run Regression Suite for Quality Gate Paths

**Files:**
- Verify: `backend/tests/test_chunk_splitter.py`
- Verify: `backend/tests/test_domain_metadata_quality_gate.py`
- Verify: `backend/tests/test_chunk_persistence_service.py`
- Verify: `backend/tests/test_index_lifecycle_service.py`
- Verify: `backend/tests/test_parser_normalization.py`

- [ ] **Step 1: Run splitter and domain gate tests**

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_parser_normalization.py -q
```

Expected: all tests pass. If additional synchronous splitter tests fail with coroutine errors, convert only the failing tests to `@pytest.mark.asyncio` and `await ChunkSplitter(...).split(...)`.

- [ ] **Step 2: Run persistence and indexing regressions**

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_persistence_service.py backend/tests/test_index_lifecycle_service.py -q
```

Expected: all tests pass. These verify nested `extraction_quality` survives DB persistence and materialization policy decisions remain compatible with existing indexing code.

- [ ] **Step 3: Run lint on changed backend files**

```bash
python -m ruff check backend/src/ragstudio/services/chunk_splitter.py backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/parser_normalization.py backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_index_lifecycle_service.py backend/tests/test_parser_normalization.py
```

Expected: no lint violations.

- [ ] **Step 4: Commit any test-only async cleanup**

If Step 1 required converting additional stale splitter tests to async, commit them separately:

```bash
git add backend/tests/test_chunk_splitter.py
git commit -m "test: await async chunk splitter regressions"
```

- [ ] **Step 5: Final status check**

```bash
git status --short
```

Expected: clean working tree, or only unrelated pre-existing user changes.

---

## Self-Review

Spec coverage:

- Warning propagation is covered by Task 1.
- Intelligent gate application during chunking decisions is covered by Task 2.
- Modal warning persistence and policy effect are covered by Task 3.
- Shared content-list de-duplication is covered by Task 4.
- Modal routing lifecycle explicitness is covered by Task 5.
- Page-boundary stitching hardening is covered by Task 6.
- Chunk persistence return ordering is covered by Task 7.
- Regression verification is covered by Task 8.

Placeholder scan:

- No task uses TBD, TODO, or unspecified test work.
- Every code-changing step includes exact target paths and concrete replacement code.

Type consistency:

- `ChunkSplitter.split()` is async in source, and new tests use `@pytest.mark.asyncio` plus `await`.
- `DomainMetadataQualityGate.merge_parser_warnings()` remains the canonical nested warning merge API.
- Modal warnings use the same `severity`, `quality_gate_action`, and `quality_gate_reason` keys consumed by `_parser_warning_blocks_materialization()`.
- `StudioModalRouter` remains the underlying modal router; Task 5 exposes the lifecycle boundary without falsely treating the current wrapper delegation as absent.
- Page-boundary stitching remains deterministic and fixture-safe; Task 6 adds domain policy and explainability without adding a live provider requirement.
- `ChunkPersistenceService._order_chunks_by_ids()` is introduced before tests consume it, and it preserves the original `chunk_ids` sequence after unordered SQL bulk refresh.
