# Parser Normalization Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic parser-normalization and quality-gate boundary so MinerU misclassifications such as Arabic text being labeled as equations are detected and preserved as structured warnings before chunks reach retrieval.

**Architecture:** Insert a `MinerUContentNormalizer` between raw MinerU `source_content_list.json` and `ChunkSplitter` page/reference chunking. The normalizer converts raw parser items into trusted `NormalizedBlock` objects, drops hallucinated parser math from text chunks unless recovered text exists, and emits machine-readable quality warnings that persist into chunk metadata and extraction quality.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing `AdapterChunk`, `DomainMetadata`, `ChunkSplitter`, `ChunkPersistenceService`, Postgres JSON metadata.

---

## Scope

This plan fixes the generic ingest boundary. It does not add Quran canonical text enrichment, does not change graph projection, and does not add a UI. Domain-specific canonical Quran enrichment can be a later plugin that consumes the same quality warnings.

The concrete failure driving this plan is:

- MinerU extracted `[2:2]`.
- MinerU classified the Arabic ayah image/text region as `equation` / `equation_interline`.
- MinerU extracted only the English translation as text.
- `ChunkSplitter` consumed raw content-list text, cleaned away bogus math, and persisted a verse chunk missing Arabic text.

The root boundary to create is:

`MinerU raw artifacts -> NormalizedBlock[] -> Quality warnings -> AdapterChunk[] -> persistence/retrieval`

## Required Pre-Execution Amendments

Before implementing the tasks below, amend the implementation details so the quality
gate is a generic parser-quality contract rather than a Quran-only anomaly patch.

1. Make `domain_metadata` an explicit argument passed into
   `ChunkSplitter._chunks_from_content_list` and the normalizer, instead of
   rediscovering it from partial chunk metadata. The quality gate must receive the
   actual ingest profile chosen for the document.

2. Treat the first milestone as parser anomaly detection and quarantine unless a
   real recovery path is added. Recovery should mean OCR/VLM crop fallback,
   alternate parser retry, or another concrete source of replacement text, not just
   accepting `recovered_text` when MinerU already provides it.

3. Add a generic `ExpectedContentProfile` contract with fields such as
   `expected_scripts`, `allowed_block_types`, `reference_patterns`,
   `content_domain`, and `parser_strictness`. Use this profile for parser-quality
   decisions instead of broad string heuristics on words like `book`, `english`, or
   `mixed`.

4. Add non-Quran regression coverage: Arabic prose misclassified as an equation,
   hadith reference text, mixed Arabic-English paragraphs, and a real math or
   science document where equation blocks must remain valid.

5. Make retrieval consume parser-quality warnings. Chunks with warnings such as
   `missing_expected_arabic`, `suspected_text_misclassified_as_equation`, or
   `recovered_text_from_misclassified_block` should affect answer confidence,
   source display, or insufficient-evidence behavior instead of only being stored.

6. Create or update the graph projection record before long-running enrichment work
   begins, using statuses such as `pending_parser_quality`,
   `blocked_parser_quality`, or `queued`. Graph projection visibility must not be
   blocked until runtime enrichment fully completes.

## Implementation Alignment Required

The task list below must be reconciled with the pre-execution amendments before
execution. As currently drafted, these are blocking architecture mismatches:

1. `domain_metadata` must not be rediscovered from partial chunk metadata inside
   `_chunks_from_content_list`. Update the splitter flow so the `domain_metadata`
   argument passed to `ChunkSplitter.split(...)` is carried explicitly into content
   list normalization and page/reference splitting.

2. `ExpectedContentProfile` must be added as a real contract, not only mentioned
   in prose. Parser-quality decisions should use profile fields such as
   `expected_scripts`, `allowed_block_types`, `reference_patterns`,
   `content_domain`, and `parser_strictness` instead of broad string matching on
   `DomainMetadata`.

3. Retrieval must consume parser-quality warnings. Add explicit retrieval/context
   behavior so warnings can affect answer confidence, source display, or
   insufficient-evidence handling. Persisting warnings without retrieval behavior is
   not enough for the promised RAG outcome.

4. Resolve the graph projection scope conflict. Either keep graph projection out of
   scope and remove the graph projection amendment, or add concrete lifecycle tasks
   that create/update a projection record before long-running runtime enrichment
   can block visibility.

5. Keep recovery language honest. Unless this plan adds OCR/VLM crop fallback,
   alternate parser retry, or another concrete replacement-text source, the first
   deliverable is parser anomaly detection and quarantine, not full text recovery.

6. Expand regression coverage to match the generic claim. Add tests for hadith
   reference text, mixed Arabic-English prose, Arabic prose misclassified as an
   equation outside Quran examples, and a real math/science document where equation
   blocks must remain valid.

## File Structure

- Create: `backend/src/ragstudio/services/parser_normalization.py`
  - Defines `NormalizedBlock`, `NormalizationWarning`, `BlockRecovery`, and `MinerUContentNormalizer`.
  - Owns raw MinerU content-list parsing, source-type classification, suspicious non-text detection, and recovery hook integration.

- Create: `backend/tests/test_parser_normalization.py`
  - Unit tests for text normalization, suspicious equation detection, recovered text, page grouping, and warning shape.

- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
  - Replaces direct raw `source_content_list.json` parsing with `MinerUContentNormalizer`.
  - Carries page-level normalization warnings into `SplitPiece.metadata["extraction_quality"]`.

- Modify: `backend/tests/test_chunk_splitter.py`
  - Regression tests proving suspicious equation text is not inserted as LaTeX, warning metadata persists, recovered text is inserted when available, and reference metadata still derives correctly.

- Modify: `backend/tests/test_chunk_persistence_service.py`
  - Regression test proving `extraction_quality` metadata survives persistence into the `chunks.extraction_quality` column.

- Optional documentation update in the final task: `docs/workflows.md`
  - Documents how to interpret `parser_quality` warnings in chunk metadata.

---

### Task 1: Create Normalized MinerU Block Model

**Files:**
- Create: `backend/src/ragstudio/services/parser_normalization.py`
- Test: `backend/tests/test_parser_normalization.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_parser_normalization.py` with this content:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_normalization import MinerUContentNormalizer


def test_normalizer_preserves_text_blocks_by_page():
    normalizer = MinerUContentNormalizer()

    blocks = normalizer.normalize_content_list(
        [
            {"type": "text", "text": "[2:2]", "page_idx": 2},
            {
                "type": "text",
                "text": "This is the Book about which there is no doubt",
                "page_idx": 2,
            },
        ],
        domain_metadata=DomainMetadata(domain="generic", document_type="document"),
    )

    assert [block.text for block in blocks] == [
        "[2:2]",
        "This is the Book about which there is no doubt",
    ]
    assert [block.page_number for block in blocks] == [3, 3]
    assert all(block.warning is None for block in blocks)


def test_normalizer_flags_equation_between_reference_and_translation_for_text_document():
    normalizer = MinerUContentNormalizer()

    blocks = normalizer.normalize_content_list(
        [
            {"type": "text", "text": "[2:2]", "page_idx": 2},
            {
                "type": "equation",
                "text": "$$\\cot \\theta = \\cos \\theta \\cos \\theta$$",
                "page_idx": 2,
                "bbox": [509, 140, 905, 164],
            },
            {
                "type": "text",
                "text": "This is the Book about which there is no doubt",
                "page_idx": 2,
            },
        ],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "arabic", "english"],
        ),
    )

    assert [block.text for block in blocks if block.text] == [
        "[2:2]",
        "This is the Book about which there is no doubt",
    ]
    suspicious = [block for block in blocks if block.warning is not None]
    assert len(suspicious) == 1
    assert suspicious[0].warning is not None
    assert suspicious[0].warning.code == "suspected_text_misclassified_as_equation"
    assert suspicious[0].warning.source_type == "equation"
    assert suspicious[0].warning.page_number == 3


def test_normalizer_uses_recovered_text_for_suspicious_non_text_block():
    normalizer = MinerUContentNormalizer()

    blocks = normalizer.normalize_content_list(
        [
            {"type": "text", "text": "[2:2]", "page_idx": 2},
            {
                "type": "equation",
                "text": "$$\\cot \\theta = \\cos \\theta \\cos \\theta$$",
                "recovered_text": "ذلك الكتاب لا ريب فيه هدى للمتقين",
                "page_idx": 2,
                "bbox": [509, 140, 905, 164],
            },
            {
                "type": "text",
                "text": "This is the Book about which there is no doubt",
                "page_idx": 2,
            },
        ],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "arabic", "english"],
        ),
    )

    assert [block.text for block in blocks if block.text] == [
        "[2:2]",
        "ذلك الكتاب لا ريب فيه هدى للمتقين",
        "This is the Book about which there is no doubt",
    ]
    recovered = blocks[1]
    assert recovered.warning is not None
    assert recovered.warning.code == "recovered_text_from_misclassified_block"
    assert recovered.recovery_source == "mineru_recovered_text"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_parser_normalization.py -q
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'ragstudio.services.parser_normalization'`.

- [ ] **Step 3: Add the normalizer implementation**

Create `backend/src/ragstudio/services/parser_normalization.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata


@dataclass(frozen=True)
class NormalizationWarning:
    code: str
    detail: str
    source_type: str
    page_number: int | None
    bbox: list[Any] | None

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "detail": self.detail,
            "source_type": self.source_type,
        }
        if self.page_number is not None:
            payload["page_number"] = self.page_number
        if self.bbox is not None:
            payload["bbox"] = self.bbox
        return payload


@dataclass(frozen=True)
class NormalizedBlock:
    text: str
    page_number: int | None
    source_type: str
    bbox: list[Any] | None = None
    warning: NormalizationWarning | None = None
    recovery_source: str | None = None

    def warning_metadata(self) -> dict[str, Any] | None:
        if self.warning is None:
            return None
        payload = self.warning.to_metadata()
        if self.recovery_source:
            payload["recovery_source"] = self.recovery_source
        return payload


class MinerUContentNormalizer:
    _REFERENCE_MARKER_RE = re.compile(r"^\s*\[\d{1,4}\s*:\s*\d{1,4}\]\s*$")
    _LATEX_NOISE_RE = re.compile(
        r"\\(?:sin|cos|tan|cot|theta|alpha|beta|pi|varphi|mathsf|flat|circ|partial)"
    )

    def normalize_content_list(
        self,
        data: list[Any],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[NormalizedBlock]:
        blocks: list[NormalizedBlock] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            source_type = str(item.get("type") or "unknown")
            page_number = self._page_number(item)
            bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else None
            text = self._text_value(item)
            recovered_text = self._recovered_text(item)

            if source_type in {"text", "paragraph"}:
                if text:
                    blocks.append(
                        NormalizedBlock(
                            text=text,
                            page_number=page_number,
                            source_type=source_type,
                            bbox=bbox,
                        )
                    )
                continue

            if self._is_suspicious_text_block(
                data,
                index=index,
                source_type=source_type,
                text=text,
                domain_metadata=domain_metadata,
            ):
                if recovered_text:
                    blocks.append(
                        NormalizedBlock(
                            text=recovered_text,
                            page_number=page_number,
                            source_type=source_type,
                            bbox=bbox,
                            warning=NormalizationWarning(
                                code="recovered_text_from_misclassified_block",
                                detail=(
                                    "Parser emitted a non-text block in a prose context; "
                                    "recovered text was used instead of raw parser text."
                                ),
                                source_type=source_type,
                                page_number=page_number,
                                bbox=bbox,
                            ),
                            recovery_source="mineru_recovered_text",
                        )
                    )
                else:
                    blocks.append(
                        NormalizedBlock(
                            text="",
                            page_number=page_number,
                            source_type=source_type,
                            bbox=bbox,
                            warning=NormalizationWarning(
                                code="suspected_text_misclassified_as_equation",
                                detail=(
                                    "Parser emitted a non-text block between prose/reference "
                                    "neighbors; raw parser text was excluded from chunk text."
                                ),
                                source_type=source_type,
                                page_number=page_number,
                                bbox=bbox,
                            ),
                        )
                    )
                continue

            if source_type not in {"image", "table", "equation", "equation_interline"} and text:
                blocks.append(
                    NormalizedBlock(
                        text=text,
                        page_number=page_number,
                        source_type=source_type,
                        bbox=bbox,
                    )
                )

        return blocks

    def _text_value(self, item: dict[str, Any]) -> str:
        value = item.get("text")
        if not isinstance(value, str) or not value.strip():
            value = item.get("content")
        if isinstance(value, dict):
            value = value.get("text") or value.get("content")
        if not isinstance(value, str):
            return ""
        return value.replace("\x00", "").strip()

    def _recovered_text(self, item: dict[str, Any]) -> str:
        value = item.get("recovered_text")
        if isinstance(value, str) and value.strip():
            return value.replace("\x00", "").strip()
        recovery = item.get("recovery")
        if isinstance(recovery, dict):
            text = recovery.get("text")
            if isinstance(text, str) and text.strip():
                return text.replace("\x00", "").strip()
        return ""

    def _page_number(self, item: dict[str, Any]) -> int | None:
        page_idx = item.get("page_idx")
        if isinstance(page_idx, int):
            return page_idx + 1
        page_number = item.get("page")
        if isinstance(page_number, int):
            return page_number
        return None

    def _is_suspicious_text_block(
        self,
        data: list[Any],
        *,
        index: int,
        source_type: str,
        text: str,
        domain_metadata: DomainMetadata,
    ) -> bool:
        if source_type not in {"equation", "equation_interline"}:
            return False
        if not self._is_text_document(domain_metadata):
            return False
        previous_text = self._neighbor_text(data, index - 1, step=-1)
        next_text = self._neighbor_text(data, index + 1, step=1)
        surrounded_by_reference_or_prose = bool(
            self._REFERENCE_MARKER_RE.match(previous_text)
            or self._REFERENCE_MARKER_RE.match(next_text)
            or (previous_text and next_text)
        )
        looks_like_parser_math_noise = bool(self._LATEX_NOISE_RE.search(text))
        return surrounded_by_reference_or_prose and looks_like_parser_math_noise

    def _neighbor_text(self, data: list[Any], index: int, *, step: int) -> str:
        while 0 <= index < len(data):
            item = data[index]
            if isinstance(item, dict):
                text = self._text_value(item)
                if text:
                    return text
            index += step
        return ""

    def _is_text_document(self, metadata: DomainMetadata) -> bool:
        values: list[str] = []
        for value in (
            metadata.domain,
            metadata.document_type,
            metadata.language,
            metadata.script,
            metadata.expected_structure,
        ):
            if isinstance(value, str):
                values.append(value.casefold())
        values.extend(tag.casefold() for tag in metadata.tags)
        joined = " ".join(values)
        if any(token in joined for token in ("math", "equation", "formula")):
            return False
        return any(
            token in joined
            for token in (
                "religion",
                "religious",
                "quran",
                "hadith",
                "legal",
                "book",
                "document",
                "arabic",
                "english",
                "mixed",
            )
        )
```

- [ ] **Step 4: Run tests to verify Task 1 passes**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_parser_normalization.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/src/ragstudio/services/parser_normalization.py backend/tests/test_parser_normalization.py
git commit -m "feat: normalize mineru content blocks"
```

---

### Task 2: Wire Normalized Blocks Into ChunkSplitter

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write failing chunk splitter tests**

Append these tests to `backend/tests/test_chunk_splitter.py`:

```python
def test_chunk_splitter_records_warning_for_misclassified_equation_text(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"[2:2]","page_idx":2},
          {
            "type":"equation",
            "text":"$$\\\\cot \\\\theta = \\\\cos \\\\theta \\\\cos \\\\theta$$",
            "bbox":[509,140,905,164],
            "page_idx":2
          },
          {
            "type":"text",
            "text":"This is the Book about which there is no doubt, a guidance for those conscious of Allah -",
            "page_idx":2
          }
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_ref": "source/auto/source.md",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "arabic", "english"],
            reference_pattern="surah_number:verse_number",
            expected_structure="parallel_text",
        ),
        parser_mode="mineru_strict",
    )

    verse = split[0]
    assert "\\cot" not in verse.text
    assert verse.metadata["reference_metadata"]["references"] == ["2:2"]
    warnings = verse.metadata["extraction_quality"]["parser_warnings"]
    assert warnings == [
        {
            "code": "suspected_text_misclassified_as_equation",
            "detail": (
                "Parser emitted a non-text block between prose/reference neighbors; "
                "raw parser text was excluded from chunk text."
            ),
            "source_type": "equation",
            "page_number": 3,
            "bbox": [509, 140, 905, 164],
        }
    ]


def test_chunk_splitter_uses_recovered_text_from_misclassified_block(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"[2:2]","page_idx":2},
          {
            "type":"equation",
            "text":"$$\\\\cot \\\\theta = \\\\cos \\\\theta \\\\cos \\\\theta$$",
            "recovered_text":"ذلك الكتاب لا ريب فيه هدى للمتقين",
            "bbox":[509,140,905,164],
            "page_idx":2
          },
          {
            "type":"text",
            "text":"This is the Book about which there is no doubt, a guidance for those conscious of Allah -",
            "page_idx":2
          }
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_ref": "source/auto/source.md",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "arabic", "english"],
            reference_pattern="surah_number:verse_number",
            expected_structure="parallel_text",
        ),
        parser_mode="mineru_strict",
    )

    verse = split[0]
    assert "ذلك الكتاب لا ريب فيه هدى للمتقين" in verse.text
    warnings = verse.metadata["extraction_quality"]["parser_warnings"]
    assert warnings[0]["code"] == "recovered_text_from_misclassified_block"
    assert warnings[0]["recovery_source"] == "mineru_recovered_text"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_records_warning_for_misclassified_equation_text backend/tests/test_chunk_splitter.py::test_chunk_splitter_uses_recovered_text_from_misclassified_block -q
```

Expected: FAIL because `ChunkSplitter` still reads raw `source_content_list.json` items directly and does not create `extraction_quality.parser_warnings`.

- [ ] **Step 3: Import and use the normalizer**

Modify imports at the top of `backend/src/ragstudio/services/chunk_splitter.py`:

```python
from ragstudio.services.parser_normalization import MinerUContentNormalizer, NormalizedBlock
```

Replace the body of `_chunks_from_content_list` from the `try` block through the page loop with this implementation:

```python
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(data, list):
            return []

        normalizer = MinerUContentNormalizer()
        domain_metadata = self._domain_metadata(chunk)
        normalized_blocks = normalizer.normalize_content_list(
            data,
            domain_metadata=domain_metadata,
        )

        page_blocks: dict[int, list[NormalizedBlock]] = {}
        for block in normalized_blocks:
            if block.page_number is None:
                continue
            page_blocks.setdefault(block.page_number, []).append(block)

        pieces: list[SplitPiece] = []
        for page in sorted(page_blocks):
            blocks = page_blocks[page]
            text = "\n\n".join(block.text for block in blocks if block.text.strip())
            if not text.strip():
                continue
            source_location = dict(chunk.source_location)
            source_location["page_start"] = page
            source_location["page_end"] = page
            metadata = dict(chunk.metadata)
            warnings = [
                warning
                for block in blocks
                if (warning := block.warning_metadata()) is not None
            ]
            if warnings:
                extraction_quality = dict(metadata.get("extraction_quality") or {})
                extraction_quality["parser_warnings"] = warnings
                metadata["extraction_quality"] = extraction_quality
            page_chunk = AdapterChunk(
                text=text,
                source_location=source_location,
                metadata=metadata,
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            reference_units = self._reference_unit_sections(page_chunk, profile)
            if reference_units:
                pieces.extend(reference_units)
                continue
            for part in self._hard_split_text(text, profile.hard_max_words):
                pieces.append(
                    self._piece_from_parent(page_chunk, part, source_location=source_location)
                )
        return pieces
```

Add this helper method near `_parser_metadata`:

```python
    def _domain_metadata(self, chunk: AdapterChunk | SplitPiece) -> DomainMetadata:
        value = chunk.metadata.get("domain_metadata")
        if isinstance(value, DomainMetadata):
            return value
        if isinstance(value, dict):
            return DomainMetadata.model_validate(value)
        return DomainMetadata()
```

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_parser_normalization.py backend/tests/test_chunk_splitter.py::test_chunk_splitter_records_warning_for_misclassified_equation_text backend/tests/test_chunk_splitter.py::test_chunk_splitter_uses_recovered_text_from_misclassified_block -q
```

Expected: PASS.

- [ ] **Step 5: Run full chunk splitter tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_splitter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_splitter.py
git commit -m "feat: route mineru chunks through parser normalizer"
```

---

### Task 3: Add Reference-Unit Quality Gate

**Files:**
- Create: `backend/src/ragstudio/services/chunk_quality_gate.py`
- Test: `backend/tests/test_chunk_quality_gate.py`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Modify: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write failing tests for generic quality warnings**

Create `backend/tests/test_chunk_quality_gate.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.chunk_quality_gate import ChunkQualityGate


def test_quality_gate_flags_missing_expected_arabic_script():
    gate = ChunkQualityGate()

    warnings = gate.evaluate_text(
        "Surah 2\n\n[2:2]\n\nThis is the Book about which there is no doubt",
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["arabic", "english"],
            reference_pattern="surah_number:verse_number",
        ),
    )

    assert warnings == [
        {
            "code": "reference_unit_missing_expected_script",
            "detail": "Reference-bearing chunk is expected to include Arabic text but contains no Arabic letters.",
            "expected_script": "arabic",
        }
    ]


def test_quality_gate_does_not_flag_arabic_present():
    gate = ChunkQualityGate()

    warnings = gate.evaluate_text(
        "Surah 2\n\n[2:2]\n\nذلك الكتاب لا ريب فيه هدى للمتقين\n\nThis is the Book",
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["arabic", "english"],
            reference_pattern="surah_number:verse_number",
        ),
    )

    assert warnings == []


def test_quality_gate_does_not_require_arabic_for_english_document():
    gate = ChunkQualityGate()

    warnings = gate.evaluate_text(
        "[2:2]\n\nThis is the Book about which there is no doubt",
        domain_metadata=DomainMetadata(
            domain="manual",
            document_type="document",
            tags=["english"],
        ),
    )

    assert warnings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_quality_gate.py -q
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'ragstudio.services.chunk_quality_gate'`.

- [ ] **Step 3: Implement the quality gate**

Create `backend/src/ragstudio/services/chunk_quality_gate.py`:

```python
from __future__ import annotations

import re
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata


class ChunkQualityGate:
    _REFERENCE_RE = re.compile(r"\[\d{1,4}\s*:\s*\d{1,4}\]")
    _ARABIC_RE = re.compile(r"[\u0600-\u06ff]")

    def evaluate_text(
        self,
        text: str,
        *,
        domain_metadata: DomainMetadata,
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if self._expects_arabic(domain_metadata) and self._REFERENCE_RE.search(text):
            if not self._ARABIC_RE.search(text):
                warnings.append(
                    {
                        "code": "reference_unit_missing_expected_script",
                        "detail": (
                            "Reference-bearing chunk is expected to include Arabic text "
                            "but contains no Arabic letters."
                        ),
                        "expected_script": "arabic",
                    }
                )
        return warnings

    def _expects_arabic(self, metadata: DomainMetadata) -> bool:
        values: list[str] = []
        for value in (metadata.language, metadata.script, metadata.domain, metadata.document_type):
            if isinstance(value, str):
                values.append(value.casefold())
        values.extend(tag.casefold() for tag in metadata.tags)
        joined = " ".join(values)
        return "arabic" in joined or "mixed" in joined
```

- [ ] **Step 4: Run quality gate tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_quality_gate.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Wire gate into split metadata**

Modify imports in `backend/src/ragstudio/services/chunk_splitter.py`:

```python
from ragstudio.services.chunk_quality_gate import ChunkQualityGate
```

Update `_with_split_metadata` after `self._enrich_metadata(...)`:

```python
        quality_warnings = ChunkQualityGate().evaluate_text(
            piece.text,
            domain_metadata=self._domain_metadata(piece),
        )
        if quality_warnings:
            extraction_quality = dict(metadata.get("extraction_quality") or {})
            existing = list(extraction_quality.get("parser_warnings") or [])
            extraction_quality["parser_warnings"] = [*existing, *quality_warnings]
            metadata["extraction_quality"] = extraction_quality
```

- [ ] **Step 6: Add chunk splitter regression for missing Arabic**

Append this test to `backend/tests/test_chunk_splitter.py`:

```python
def test_chunk_splitter_flags_reference_chunk_missing_expected_arabic():
    chunk = AdapterChunk(
        text="Surah 2\n\n[2:2]\n\nThis is the Book about which there is no doubt.",
        source_location={"artifact": "source/auto/source.md", "page_start": 3, "page_end": 3},
        metadata={
            "parser_metadata": {"backend": "mineru", "chunk_index": 0},
            "domain_metadata": {
                "domain": "religion",
                "document_type": "religious_text",
                "tags": ["quran", "arabic", "english"],
                "reference_pattern": "surah_number:verse_number",
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "arabic", "english"],
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    warnings = split[0].metadata["extraction_quality"]["parser_warnings"]
    assert {
        "code": "reference_unit_missing_expected_script",
        "detail": (
            "Reference-bearing chunk is expected to include Arabic text "
            "but contains no Arabic letters."
        ),
        "expected_script": "arabic",
    } in warnings
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_quality_gate.py backend/tests/test_chunk_splitter.py::test_chunk_splitter_flags_reference_chunk_missing_expected_arabic -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add backend/src/ragstudio/services/chunk_quality_gate.py backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_quality_gate.py backend/tests/test_chunk_splitter.py
git commit -m "feat: flag reference chunks missing expected script"
```

---

### Task 4: Prove Quality Metadata Persists

**Files:**
- Modify: `backend/tests/test_chunk_persistence_service.py`

- [ ] **Step 1: Add failing persistence test**

Append this test to `backend/tests/test_chunk_persistence_service.py`:

```python
@pytest.mark.asyncio
async def test_chunk_persistence_preserves_parser_quality_warnings(client):
    from ragstudio.db.models import Document
    from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
    from ragstudio.services.adapter import AdapterChunk
    from ragstudio.services.chunk_persistence_service import ChunkPersistenceService

    session = client.app.state.session_factory()
    async with session:
        document = Document(
            id="doc-quality-warning",
            filename="quality.pdf",
            content_type="application/pdf",
            sha256="quality-warning-sha",
            artifact_path="/tmp/quality.pdf",
            status="running",
        )
        session.add(document)
        await session.flush()
        service = ChunkPersistenceService(session)
        chunks = await service.persist(
            document,
            [
                AdapterChunk(
                    text="[2:2]\n\nThis is the Book about which there is no doubt.",
                    metadata={
                        "parser_metadata": {"backend": "mineru", "chunk_index": 0},
                        "extraction_quality": {
                            "parser_warnings": [
                                {
                                    "code": "reference_unit_missing_expected_script",
                                    "detail": (
                                        "Reference-bearing chunk is expected to include Arabic text "
                                        "but contains no Arabic letters."
                                    ),
                                    "expected_script": "arabic",
                                }
                            ]
                        },
                    },
                    source_location={"page_start": 3, "page_end": 3},
                )
            ],
            IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=DomainMetadata(tags=["arabic", "english"]),
            ),
            commit=False,
        )

        assert chunks[0].extraction_quality["parser_warnings"][0]["code"] == (
            "reference_unit_missing_expected_script"
        )
```

- [ ] **Step 2: Run test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_persistence_service.py::test_chunk_persistence_preserves_parser_quality_warnings -q
```

Expected: PASS. The current persistence service already copies `metadata["extraction_quality"]` into `chunks.extraction_quality`; this test locks that behavior.

- [ ] **Step 3: Commit Task 4**

```bash
git add backend/tests/test_chunk_persistence_service.py
git commit -m "test: preserve parser quality warnings"
```

---

### Task 5: Add Job-Level Warning Summary

**Files:**
- Modify: `backend/src/ragstudio/services/document_service.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Add failing lifecycle test**

Append this test to `backend/tests/test_mineru_reindex_jobs.py`:

```python
@pytest.mark.asyncio
async def test_index_job_result_includes_parser_quality_warning_summary(client, monkeypatch):
    from ragstudio.db.models import Chunk, Document, Job
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.document_service import DocumentService

    app = client.app
    async with app.state.session_factory() as session:
        document = Document(
            id="doc-parser-warning-summary",
            filename="parser-warning.pdf",
            content_type="application/pdf",
            sha256="parser-warning-sha",
            artifact_path="/tmp/parser-warning.pdf",
            status=StageStatus.READY.value,
        )
        job = Job(
            id="job-parser-warning-summary",
            type="index_document",
            target_id=document.id,
            status=StageStatus.READY.value,
            progress=0,
            logs=[],
            result={},
        )
        session.add_all([document, job])
        await session.commit()

        async def fake_reindex_document(*args, **kwargs):
            chunk = Chunk(
                id="chunk-parser-warning-summary",
                document_id=document.id,
                text="[2:2]\n\nThis is the Book about which there is no doubt.",
                text_search_ar="",
                tokens_ar=[],
                extraction_quality={
                    "parser_warnings": [
                        {
                            "code": "reference_unit_missing_expected_script",
                            "detail": (
                                "Reference-bearing chunk is expected to include Arabic text "
                                "but contains no Arabic letters."
                            ),
                            "expected_script": "arabic",
                        }
                    ]
                },
                source_location={"page_start": 3, "page_end": 3},
                metadata_json={},
                content_type="text",
            )
            return type(
                "LifecycleResult",
                (),
                {
                    "chunks": [chunk],
                    "graph_materialization": {"status": "skipped", "reason": "test"},
                },
            )()

        monkeypatch.setattr(
            "ragstudio.services.index_lifecycle_service.IndexLifecycleService.reindex_document",
            fake_reindex_document,
        )

        service = DocumentService(session, app.state.store, settings=app.state.settings)
        await service._index_document_for_job(document, job)

        assert job.result["parser_quality"]["warning_counts"] == {
            "reference_unit_missing_expected_script": 1
        }
        assert "Parser quality warnings: reference_unit_missing_expected_script=1" in job.logs
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_mineru_reindex_jobs.py::test_index_job_result_includes_parser_quality_warning_summary -q
```

Expected: FAIL because `DocumentService` does not summarize chunk parser warnings into job results.

- [ ] **Step 3: Add warning summary helper**

In `backend/src/ragstudio/services/document_service.py`, add this helper method inside `DocumentService` near `_record_graph_materialization_warning`:

```python
    def _record_parser_quality_summary(self, job: Job, chunks: list[Any]) -> None:
        counts: dict[str, int] = {}
        for chunk in chunks:
            extraction_quality = getattr(chunk, "extraction_quality", None)
            if not isinstance(extraction_quality, dict):
                continue
            warnings = extraction_quality.get("parser_warnings")
            if not isinstance(warnings, list):
                continue
            for warning in warnings:
                if not isinstance(warning, dict):
                    continue
                code = warning.get("code")
                if isinstance(code, str) and code:
                    counts[code] = counts.get(code, 0) + 1
        if not counts:
            return
        result = job.result or {}
        job.result = {
            **result,
            "parser_quality": {
                "warning_counts": dict(sorted(counts.items())),
            },
        }
        summary = ", ".join(f"{code}={count}" for code, count in sorted(counts.items()))
        job.logs = [*(job.logs or []), f"Parser quality warnings: {summary}"]
```

Call the helper in `_index_document_for_job` immediately after `chunk_count = len(chunks or [])`:

```python
        self._record_parser_quality_summary(job, list(chunks or []))
```

- [ ] **Step 4: Run focused test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_mineru_reindex_jobs.py::test_index_job_result_includes_parser_quality_warning_summary -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add backend/src/ragstudio/services/document_service.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "feat: summarize parser quality warnings in jobs"
```

---

### Task 6: Add Regression Fixture For The Observed Quran Failure Shape

**Files:**
- Modify: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Add exact-shape regression test**

Append this test to `backend/tests/test_chunk_splitter.py`:

```python
def test_quran_like_mineru_equation_gap_is_flagged_without_quran_specific_fix(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"Surah 2","page_idx":2},
          {"type":"text","text":"[2:2]","page_idx":2},
          {
            "type":"equation",
            "text":"$$\\\\cot \\\\theta = \\\\cos \\\\theta \\\\cos \\\\theta \\\\cos \\\\theta$$",
            "text_format":"latex",
            "bbox":[509,140,905,164],
            "page_idx":2
          },
          {
            "type":"text",
            "text":"This is the Book about which there is no doubt, a guidance for those conscious of Allah -",
            "bbox":[91,176,738,193],
            "page_idx":2
          }
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_ref": "source/auto/source.md",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            },
            "domain_metadata": {
                "domain": "religion",
                "document_type": "religious_text",
                "tags": ["quran", "arabic", "english"],
                "reference_pattern": "surah_number:verse_number",
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "arabic", "english"],
            reference_pattern="surah_number:verse_number",
            expected_structure="parallel_text",
        ),
        parser_mode="mineru_strict",
    )

    verse = next(item for item in split if item.metadata["reference_metadata"]["references"] == ["2:2"])
    warning_codes = {
        warning["code"]
        for warning in verse.metadata["extraction_quality"]["parser_warnings"]
    }
    assert warning_codes == {
        "suspected_text_misclassified_as_equation",
        "reference_unit_missing_expected_script",
    }
    assert "\\cot" not in verse.text
    assert "This is the Book about which there is no doubt" in verse.text
```

- [ ] **Step 2: Run exact regression test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_splitter.py::test_quran_like_mineru_equation_gap_is_flagged_without_quran_specific_fix -q
```

Expected: PASS.

- [ ] **Step 3: Commit Task 6**

```bash
git add backend/tests/test_chunk_splitter.py
git commit -m "test: cover quran-like mineru equation gap"
```

---

### Task 7: Documentation And Full Verification

**Files:**
- Modify: `docs/workflows.md`

- [ ] **Step 1: Add parser quality documentation**

Add this section to `docs/workflows.md` under the ingestion or document-indexing workflow section:

```markdown
## Parser Quality Warnings

Ragstudio treats parser output as untrusted input. MinerU item labels such as
`text`, `equation`, `table`, and `image` are normalized before chunking.

Parser warnings are persisted in chunk metadata under:

`metadata_json.extraction_quality.parser_warnings`

and copied to the `chunks.extraction_quality` column.

Common warning codes:

- `suspected_text_misclassified_as_equation`: MinerU emitted a non-text block in a prose/reference context, usually a sign that OCR classified text as math.
- `recovered_text_from_misclassified_block`: a suspicious non-text block had recovered text and the recovered text was used in the chunk.
- `reference_unit_missing_expected_script`: a reference-bearing chunk is expected to include a script such as Arabic, but the chunk text does not contain that script.

When these warnings appear, retrieval may still work for translation or metadata queries,
but exact source-language phrase search can miss the intended chunk until the source text is recovered.
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_parser_normalization.py backend/tests/test_chunk_quality_gate.py backend/tests/test_chunk_splitter.py backend/tests/test_chunk_persistence_service.py::test_chunk_persistence_preserves_parser_quality_warnings backend/tests/test_mineru_reindex_jobs.py::test_index_job_result_includes_parser_quality_warning_summary -q
```

Expected: PASS.

- [ ] **Step 3: Run wider ingestion/retrieval suite**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_chunk_splitter.py backend/tests/test_chunk_persistence_service.py backend/tests/test_mineru_reindex_jobs.py backend/tests/test_reference_metadata.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 4: Check formatting and whitespace**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Commit Task 7**

```bash
git add docs/workflows.md
git commit -m "docs: explain parser quality warnings"
```

---

## Manual Validation After Implementation

- [ ] Re-index `quran_arabic_english.pdf` in local Ragstudio.
- [ ] Query Postgres for the `2:2` chunk:

```bash
docker compose exec -T postgres psql -U ragstudio -d ragstudio -c "select c.id, c.extraction_quality, c.text from chunks c join documents d on d.id=c.document_id where d.filename='quran_arabic_english.pdf' and c.metadata_json #>> '{reference_metadata,references,0}' = '2:2' limit 1;"
```

Expected:

- `extraction_quality.parser_warnings` includes `suspected_text_misclassified_as_equation`.
- `extraction_quality.parser_warnings` includes `reference_unit_missing_expected_script` unless recovered Arabic text was supplied before chunking.
- The chunk text does not contain hallucinated LaTeX such as `\cot \theta`.

- [ ] Confirm exact Arabic phrase behavior:

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"ذلك الكتاب لا ريب فيه هدى للمتقين","document_ids":["07fc5d41-7b14-4367-9d4c-d2151b02378b"],"variant_ids":["3850497f-9cbc-43fb-87af-4e3a1c35acd7"],"limit":3}'
```

Expected:

- If recovered Arabic text was not supplied, the answer should show insufficient direct Arabic evidence and chunk metadata should explain why.
- If recovered Arabic text was supplied in the normalized block, the top evidence should include the `2:2` chunk.

## Self-Review

- Spec coverage: The plan covers parser mistrust, generic normalization, suspicious non-text detection, recovered text handling, reference/script quality gates, persistence, job-level summaries, and tests using the observed Quran failure shape.
- Placeholder scan: The plan contains no `TBD`, no deferred implementation markers, and no unnamed validation steps.
- Type consistency: `NormalizedBlock`, `NormalizationWarning`, `MinerUContentNormalizer`, and `ChunkQualityGate` are defined before they are used by `ChunkSplitter` and tests.
- Scope check: The plan intentionally excludes Quran canonical enrichment and graph Cypher repair because those are independent subsystems.
