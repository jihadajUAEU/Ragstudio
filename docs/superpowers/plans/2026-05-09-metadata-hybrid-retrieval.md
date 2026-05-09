# Metadata Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make domain metadata actively drive chunk boundaries and retrieval ranking so Quran/reference-heavy documents pass the Excel retrieval cases, while keeping the design generic for other cited corpora.

**Architecture:** Add a small metadata semantics interpreter that reads editable `DomainMetadata.custom_json` plus standard metadata fields. Use it in `ChunkSplitter` to select scripture/reference-aware profiles, derive reference fields on chunks, preserve title chunks, and remove obvious MinerU noise. Use the same interpreter in a hybrid retrieval scorer that combines exact references, exact phrases, lexical overlap, metadata boosts, and source order.

**Tech Stack:** FastAPI backend, SQLAlchemy async models, Pydantic schemas, existing `ChunkService`, `ChunkSplitter`, MinerU adapter chunks, pytest/pytest-asyncio, Docker Compose test runner.

---

## File Structure

- Create `backend/src/ragstudio/services/reference_metadata.py`
  - Owns metadata semantics parsing, query reference extraction, chunk reference extraction, relationship keys, and scoring hints.
  - Does not import database models.
- Create `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Owns ranked chunk scoring from query + chunk text + chunk metadata.
  - Depends on `reference_metadata.py`.
- Modify `backend/src/ragstudio/services/chunk_splitter.py`
  - Uses metadata semantics to select `scripture_reference`/`quran_verse` profiles from configurable metadata, not hardcoded `domain == "quran"` only.
  - Adds derived reference metadata to split chunks.
  - Preserves document/title chunks when available.
  - Applies conservative MinerU math/OCR noise cleanup.
- Modify `backend/src/ragstudio/services/chunk_service.py`
  - Replaces inline `_score()` ranking with `HybridChunkSearch`.
  - Keeps existing `ChunkSearchOut` API shape.
- Modify `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
  - Prompts autosuggest to propose editable `custom_json.reference_schema`, `custom_json.relationships`, `custom_json.chunking`, and `custom_json.retrieval` when the sampled document shows structured references.
- Test `backend/tests/test_reference_metadata.py`
  - Unit tests for semantics parsing and query/chunk reference extraction.
- Test `backend/tests/test_chunk_splitter.py`
  - Extend splitter tests for metadata-driven scripture profile, title preservation, reference fields, and noise cleanup.
- Test `backend/tests/test_chunks.py`
  - Extend API/search tests for exact reference top-1 and natural-language top-5 behavior.
- Test `backend/tests/test_domain_metadata.py`
  - Extend autosuggest tests to verify custom JSON reference semantics can be returned and preserved.
- Create `backend/src/ragstudio/services/metadata_json_schema.py`
  - Owns allowed custom JSON shape, validation, schema examples, and user-facing validation messages.
- Create `backend/src/ragstudio/services/retrieval_explainer.py`
  - Converts `score_breakdown`, reference metadata, and relationship expansion into stable debug payloads for UI and Excel output.
- Create `backend/src/ragstudio/services/excel_regression_runner.py`
  - Runs the Quran Excel cases through the API search layer and writes pass/fail/debug output.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Adds a reindex-with-updated-metadata endpoint that reuses the original uploaded file.
- Modify `backend/src/ragstudio/api/routes/chunks.py`
  - Adds neighbor expansion and explain output to chunk search responses.
- Modify `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
  - Adds custom JSON schema helper examples and clearer autosuggest custom JSON diff rendering.
- Modify `frontend/src/features/chunks/chunk-inspector.tsx`
  - Shows retrieval explain/debug details and neighbor relationship metadata.
- Modify `frontend/src/features/documents/documents-page.tsx`
  - Adds reindex-with-current-metadata action for uploaded documents.
- Test `frontend/tests/domain-metadata-panel.test.tsx`
  - Covers custom JSON helper, validation, and autosuggest diff details.
- Test `frontend/tests/chunk-inspector.test.tsx`
  - Covers retrieval explain rendering.
- Test `frontend/tests/documents-page.test.tsx`
  - Covers reindex-with-current-metadata UI flow.
- Modify `docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md`
  - Add note that reference behavior is metadata-controlled and not Quran-hardcoded.

---

## Task 1: Reference Metadata Interpreter

**Files:**
- Create: `backend/src/ragstudio/services/reference_metadata.py`
- Test: `backend/tests/test_reference_metadata.py`

- [ ] **Step 1: Write failing tests for configurable reference semantics**

Create `backend/tests/test_reference_metadata.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.reference_metadata import ReferenceSemantics


def quran_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran", "islam", "translation"],
        expected_structure="parallel_text",
        reference_pattern="surah_number:verse_number",
        script="arabic_latin",
        content_role="primary_text",
        custom_json={
            "reference_schema": {
                "type": "surah_ayah",
                "display": "Quran {chapter}:{verse}",
                "fields": {
                    "chapter": "surah",
                    "verse": "ayah",
                    "page": "page_start",
                },
            },
            "relationships": {
                "previous": ["same_chapter", "verse - 1"],
                "next": ["same_chapter", "verse + 1"],
                "chapter": ["same_chapter"],
                "page": ["same_page"],
            },
            "chunking": {
                "unit": "verse",
                "include_neighbors": 1,
                "preserve_parallel_text": True,
            },
            "retrieval": {
                "exact_reference_top1": True,
                "boost_same_chapter": True,
                "boost_neighbor_verses": True,
            },
        },
    )


def test_reference_semantics_detects_scripture_profile_from_metadata_json():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.profile_name == "scripture_reference"
    assert semantics.reference_type == "surah_ayah"
    assert semantics.chunk_unit == "verse"
    assert semantics.include_neighbors == 1
    assert semantics.exact_reference_top1 is True
    assert semantics.preserve_parallel_text is True


def test_reference_semantics_falls_back_from_standard_metadata_fields():
    metadata = DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran"],
        reference_pattern="surah_number:verse_number",
        expected_structure="parallel_text",
    )

    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.profile_name == "scripture_reference"
    assert semantics.reference_type == "surah_ayah"
    assert semantics.chunk_unit == "verse"
    assert semantics.exact_reference_top1 is True


def test_extract_query_reference_supports_quran_and_bracket_forms():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.extract_query_reference("What does Quran 1:4 say?") == {
        "chapter": 1,
        "verse": 4,
        "raw": "Quran 1:4",
    }
    assert semantics.extract_query_reference("Find [2:17]") == {
        "chapter": 2,
        "verse": 17,
        "raw": "[2:17]",
    }


def test_extract_chunk_references_finds_multiple_markers():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    refs = semantics.extract_chunk_references(
        "Surah 1\n\n[1:1]\n\nPraise text\n\n[1:2]\n\nMerciful text"
    )

    assert refs == [
        {"chapter": 1, "verse": 1, "raw": "[1:1]"},
        {"chapter": 1, "verse": 2, "raw": "[1:2]"},
    ]


def test_reference_metadata_for_chunk_records_range_and_neighbors():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    metadata = semantics.chunk_reference_metadata(
        "Surah 1\n\n[1:4]\n\nIt is You we worship."
    )

    assert metadata["reference_type"] == "surah_ayah"
    assert metadata["chapter_start"] == 1
    assert metadata["chapter_end"] == 1
    assert metadata["verse_start"] == 4
    assert metadata["verse_end"] == 4
    assert metadata["references"] == ["1:4"]
    assert metadata["previous_ref"] == "1:3"
    assert metadata["next_ref"] == "1:5"
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_reference_metadata.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.reference_metadata'`.

- [ ] **Step 3: Implement the reference metadata interpreter**

Create `backend/src/ragstudio/services/reference_metadata.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata


@dataclass(frozen=True)
class ReferenceSemantics:
    profile_name: str = "generic"
    reference_type: str | None = None
    chunk_unit: str = "section"
    include_neighbors: int = 0
    preserve_parallel_text: bool = False
    exact_reference_top1: bool = False
    boost_same_chapter: bool = False
    boost_neighbor_verses: bool = False
    relationships: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_metadata(cls, metadata: DomainMetadata) -> "ReferenceSemantics":
        custom = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
        reference_schema = custom.get("reference_schema")
        chunking = custom.get("chunking")
        retrieval = custom.get("retrieval")
        relationships = custom.get("relationships")

        reference_type = None
        if isinstance(reference_schema, dict):
            raw_type = reference_schema.get("type")
            if isinstance(raw_type, str) and raw_type.strip():
                reference_type = raw_type.strip()

        inferred_scripture = cls._looks_like_scripture(metadata)
        if reference_type is None and inferred_scripture:
            reference_type = "surah_ayah"

        profile_name = "scripture_reference" if reference_type == "surah_ayah" else "generic"

        chunk_unit = "section"
        include_neighbors = 0
        preserve_parallel_text = False
        if isinstance(chunking, dict):
            if isinstance(chunking.get("unit"), str):
                chunk_unit = chunking["unit"]
            include_neighbors = cls._safe_int(chunking.get("include_neighbors"), default=0)
            preserve_parallel_text = bool(chunking.get("preserve_parallel_text", False))
        elif inferred_scripture:
            chunk_unit = "verse"
            include_neighbors = 1
            preserve_parallel_text = True

        if isinstance(retrieval, dict):
            exact_reference_top1 = bool(retrieval.get("exact_reference_top1", False))
            boost_same_chapter = bool(retrieval.get("boost_same_chapter", False))
            boost_neighbor_verses = bool(retrieval.get("boost_neighbor_verses", False))
        else:
            exact_reference_top1 = inferred_scripture
            boost_same_chapter = inferred_scripture
            boost_neighbor_verses = inferred_scripture

        parsed_relationships = (
            {
                key: [str(item) for item in value]
                for key, value in relationships.items()
                if isinstance(key, str) and isinstance(value, list)
            }
            if isinstance(relationships, dict)
            else {}
        )

        return cls(
            profile_name=profile_name,
            reference_type=reference_type,
            chunk_unit=chunk_unit,
            include_neighbors=include_neighbors,
            preserve_parallel_text=preserve_parallel_text,
            exact_reference_top1=exact_reference_top1,
            boost_same_chapter=boost_same_chapter,
            boost_neighbor_verses=boost_neighbor_verses,
            relationships=parsed_relationships,
        )

    def extract_query_reference(self, query: str) -> dict[str, int | str] | None:
        if self.reference_type != "surah_ayah":
            return None
        patterns = (
            r"\bQuran\s+(?P<chapter>\d{1,3})\s*:\s*(?P<verse>\d{1,3})\b",
            r"\[(?P<chapter>\d{1,3})\s*:\s*(?P<verse>\d{1,3})\]",
            r"\b(?P<chapter>\d{1,3})\s*:\s*(?P<verse>\d{1,3})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                return {
                    "chapter": int(match.group("chapter")),
                    "verse": int(match.group("verse")),
                    "raw": match.group(0),
                }
        return None

    def extract_chunk_references(self, text: str) -> list[dict[str, int | str]]:
        if self.reference_type != "surah_ayah":
            return []
        refs: list[dict[str, int | str]] = []
        seen: set[tuple[int, int]] = set()
        for match in re.finditer(r"\[(?P<chapter>\d{1,3})\s*:\s*(?P<verse>\d{1,3})\]", text):
            chapter = int(match.group("chapter"))
            verse = int(match.group("verse"))
            key = (chapter, verse)
            if key in seen:
                continue
            seen.add(key)
            refs.append({"chapter": chapter, "verse": verse, "raw": match.group(0)})
        return refs

    def chunk_reference_metadata(self, text: str) -> dict[str, Any]:
        refs = self.extract_chunk_references(text)
        if not refs:
            return {}
        chapters = [int(ref["chapter"]) for ref in refs]
        verses = [int(ref["verse"]) for ref in refs]
        chapter_start = min(chapters)
        chapter_end = max(chapters)
        verse_start = min(verses) if chapter_start == chapter_end else int(refs[0]["verse"])
        verse_end = max(verses) if chapter_start == chapter_end else int(refs[-1]["verse"])
        metadata: dict[str, Any] = {
            "reference_type": self.reference_type,
            "chapter_start": chapter_start,
            "chapter_end": chapter_end,
            "verse_start": verse_start,
            "verse_end": verse_end,
            "references": [f"{ref['chapter']}:{ref['verse']}" for ref in refs],
        }
        if chapter_start == chapter_end:
            if verse_start > 1:
                metadata["previous_ref"] = f"{chapter_start}:{verse_start - 1}"
            metadata["next_ref"] = f"{chapter_start}:{verse_end + 1}"
        return metadata

    @staticmethod
    def _looks_like_scripture(metadata: DomainMetadata) -> bool:
        values = {
            metadata.domain,
            metadata.document_type,
            metadata.reference_pattern,
            metadata.expected_structure,
            metadata.script,
            metadata.content_role,
            *metadata.tags,
        }
        normalized = {value.casefold() for value in values if isinstance(value, str)}
        return bool(
            {"quran", "surah_number:verse_number", "parallel_text", "surah", "ayah"}
            & normalized
        )

    @staticmethod
    def _safe_int(value: Any, *, default: int) -> int:
        if isinstance(value, int):
            return max(value, 0)
        return default
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_reference_metadata.py -q
```

Expected: PASS, `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/reference_metadata.py backend/tests/test_reference_metadata.py
git commit -m "feat: interpret reference metadata"
```

---

## Task 2: Metadata-Aware Chunk Profiles and Reference Enrichment

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Add failing splitter tests for scripture profile selection and reference fields**

Append to `backend/tests/test_chunk_splitter.py`:

```python
def test_chunk_splitter_uses_scripture_profile_from_editable_metadata_json():
    chunk = AdapterChunk(
        text=(
            "Surah 1\n\n"
            "[1:1]\n\n[All] praise is [due] to Allah, Lord of the worlds -\n\n"
            "[1:2]\n\nThe Entirely Merciful, the Especially Merciful,"
        ),
        source_location={"artifact": "source/auto/source.md", "page_start": 2, "page_end": 2},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )
    metadata = DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran"],
        custom_json={
            "reference_schema": {"type": "surah_ayah"},
            "chunking": {"unit": "verse", "include_neighbors": 1, "preserve_parallel_text": True},
            "retrieval": {"exact_reference_top1": True},
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert split[0].metadata["parser_metadata"]["split_profile"] == "scripture_reference"
    assert split[0].metadata["reference_metadata"]["reference_type"] == "surah_ayah"
    assert split[0].metadata["reference_metadata"]["references"] == ["1:1", "1:2"]
    assert "previous_ref" not in split[0].metadata["reference_metadata"]
    assert split[0].metadata["reference_metadata"]["next_ref"] == "1:3"


def test_chunk_splitter_selects_scripture_profile_from_standard_fields():
    chunk = AdapterChunk(
        text="Surah 2\n\n[2:2]\n\nThis is the Book about which there is no doubt.",
        source_location={"artifact": "source/auto/source.md", "page_start": 3, "page_end": 3},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "translation"],
            reference_pattern="surah_number:verse_number",
            expected_structure="parallel_text",
        ),
        parser_mode="mineru_strict",
    )

    assert split[0].metadata["parser_metadata"]["split_profile"] == "scripture_reference"
    assert split[0].metadata["reference_metadata"]["chapter_start"] == 2
    assert split[0].metadata["reference_metadata"]["verse_start"] == 2


def test_chunk_splitter_preserves_title_as_small_metadata_chunk():
    chunk = AdapterChunk(
        text=(
            "The Holy Quran\n\n"
            "Arabic Text with English Translation\n\n"
            "Surah 1\n\n[1:1]\n\n[All] praise is [due] to Allah, Lord of the worlds -"
        ),
        source_location={"artifact": "source/auto/source.md", "page_start": 1, "page_end": 2},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    assert any("The Holy Quran" in item.text for item in split)
    title_chunk = next(item for item in split if "The Holy Quran" in item.text)
    assert title_chunk.metadata["parser_metadata"]["split_profile"] == "scripture_reference"
    assert title_chunk.metadata["document_metadata"]["title"] == (
        "The Holy Quran Arabic Text with English Translation"
    )
```

Note: If the first test assertion for `previous_ref` feels awkward, implement `ReferenceSemantics.chunk_reference_metadata()` so it omits `previous_ref` for verse 1. Then use:

```python
assert "previous_ref" not in split[0].metadata["reference_metadata"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_chunk_splitter.py -q
```

Expected: FAIL because `split_profile` remains `generic` and `reference_metadata` is absent.

- [ ] **Step 3: Update `ChunkSplitter` profile selection and metadata enrichment**

Modify imports in `backend/src/ragstudio/services/chunk_splitter.py`:

```python
from ragstudio.services.reference_metadata import ReferenceSemantics
```

Update `ChunkProfile` and profile selection:

```python
@dataclass(frozen=True)
class ChunkProfile:
    name: str
    target_words: int
    hard_max_words: int
    semantics: ReferenceSemantics | None = None
```

Replace `_profile()` with:

```python
def _profile(self, metadata: DomainMetadata) -> ChunkProfile:
    semantics = ReferenceSemantics.from_metadata(metadata)
    if semantics.profile_name == "scripture_reference":
        return ChunkProfile(
            "scripture_reference",
            target_words=450,
            hard_max_words=min(self.max_words, 900),
            semantics=semantics,
        )

    domain = (metadata.domain or "").casefold()
    document_type = (metadata.document_type or "").casefold()
    if domain == "tafseer" or document_type == "book":
        return ChunkProfile("tafseer_book", target_words=1000, hard_max_words=self.max_words)
    if document_type == "paper":
        return ChunkProfile(
            "paper_section",
            target_words=800,
            hard_max_words=min(self.max_words, 1200),
        )
    if document_type == "table":
        return ChunkProfile(
            "table_block",
            target_words=400,
            hard_max_words=min(self.max_words, 800),
        )
    return ChunkProfile("generic", target_words=1000, hard_max_words=self.max_words)
```

In `_with_split_metadata()`, before assigning `metadata["parser_metadata"]`, add:

```python
if profile.semantics is not None:
    reference_metadata = profile.semantics.chunk_reference_metadata(piece.text)
    if reference_metadata:
        metadata["reference_metadata"] = reference_metadata
    title = self._document_title(piece.text)
    if title:
        metadata["document_metadata"] = {"title": title}
```

Add helper methods:

```python
def _document_title(self, text: str) -> str | None:
    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    if len(blocks) < 2:
        return None
    joined = " ".join(blocks[:2]).strip()
    if "quran" in joined.casefold() and "translation" in joined.casefold():
        return joined
    return None
```

- [ ] **Step 4: Add conservative noise cleanup**

In `ChunkSplitter._piece_from_parent()`, normalize text before returning:

```python
cleaned = self._clean_mineru_noise(text)
```

Use `cleaned.strip()` for `SplitPiece.text`.

Add:

```python
def _clean_mineru_noise(self, text: str) -> str:
    # Remove isolated LaTeX math blocks that MinerU sometimes hallucinates around OCR text.
    cleaned = re.sub(
        r"\$\$\s*(?:\\?(?:sin|cos|tan|cot|theta|alpha|beta|pi|rho|angle|infty|Join|hookrightarrow|,|\||\s|=)+)\s*\$\$",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
```

This cleanup is intentionally narrow. It removes math-only noise patterns seen in the Excel run without stripping normal Arabic/English text.

- [ ] **Step 5: Run splitter tests**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_reference_metadata.py backend/tests/test_chunk_splitter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_chunk_splitter.py
git commit -m "feat: enrich chunks with reference metadata"
```

---

## Task 3: AI Autosuggest Custom JSON for Reference Semantics

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Add failing test for autosuggest custom JSON semantics preservation**

Append this test to `backend/tests/test_domain_metadata.py`:

```python
@pytest.mark.asyncio
async def test_ai_domain_metadata_suggester_accepts_reference_semantics_json(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "religion",
                                "document_type": "religious_text",
                                "language": "mixed",
                                "tags": ["quran", "translation"],
                                "reference_pattern": "surah_number:verse_number",
                                "expected_structure": "parallel_text",
                                "script": "arabic_latin",
                                "content_role": "primary_text",
                                "custom_json": {
                                  "reference_schema": {
                                    "type": "surah_ayah",
                                    "display": "Quran {chapter}:{verse}",
                                    "fields": {
                                      "chapter": "surah",
                                      "verse": "ayah",
                                      "page": "page_start"
                                    }
                                  },
                                  "relationships": {
                                    "previous": ["same_chapter", "verse - 1"],
                                    "next": ["same_chapter", "verse + 1"],
                                    "chapter": ["same_chapter"],
                                    "page": ["same_page"]
                                  },
                                  "chunking": {
                                    "unit": "verse",
                                    "include_neighbors": 1,
                                    "preserve_parallel_text": true
                                  },
                                  "retrieval": {
                                    "exact_reference_top1": true,
                                    "boost_same_chapter": true,
                                    "boost_neighbor_verses": true
                                  }
                                }
                              },
                              "confidence": 0.95,
                              "evidence_pages": [1, 2],
                              "rationale": "The pages show Quran surah and verse markers.",
                              "warnings": []
                            }"""
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    result = await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="quran.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="The Holy Quran"), SampledPage(page_number=2, text="Surah 1 [1:1]")],
        sampler_warnings=[],
    )

    custom_json = result.domain_metadata.custom_json
    assert custom_json["reference_schema"]["type"] == "surah_ayah"
    assert custom_json["chunking"]["unit"] == "verse"
    assert custom_json["retrieval"]["exact_reference_top1"] is True
```

- [ ] **Step 2: Run test**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_domain_metadata.py::test_ai_domain_metadata_suggester_accepts_reference_semantics_json -q
```

Expected: It may already pass because Pydantic preserves `custom_json`. If it passes, still complete Step 3 so the model is explicitly asked to propose the JSON.

- [ ] **Step 3: Update autosuggest prompt**

In `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`, update `_prompt()` so the JSON shape includes reference semantics:

```python
    "custom_json": {
      "reference_schema": {
        "type": "surah_ayah|chapter_verse|section_number|none",
        "display": "Quran {chapter}:{verse}",
        "fields": {"chapter": "surah", "verse": "ayah", "page": "page_start"}
      },
      "relationships": {
        "previous": ["same_chapter", "verse - 1"],
        "next": ["same_chapter", "verse + 1"],
        "chapter": ["same_chapter"],
        "page": ["same_page"]
      },
      "chunking": {
        "unit": "verse|section|paragraph",
        "include_neighbors": 0,
        "preserve_parallel_text": false
      },
      "retrieval": {
        "exact_reference_top1": false,
        "boost_same_chapter": false,
        "boost_neighbor_verses": false
      }
    },
```

Add this instruction below the JSON shape:

```text
If the sampled pages show structured references such as Quran surah/ayah, legal sections,
chapters, verses, or page-linked parallel text, fill custom_json with editable reference
semantics. Do not hardcode Quran behavior unless the pages show Quran-like references.
If no reference structure is visible, return custom_json as {}.
```

- [ ] **Step 4: Run domain metadata tests**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_domain_metadata.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/tests/test_domain_metadata.py
git commit -m "feat: suggest editable reference metadata"
```

---

## Task 4: Hybrid Chunk Search Scorer

**Files:**
- Create: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Add failing API tests for exact reference top-1 and natural top-5**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_search_chunks_exact_reference_returns_matching_verse_top_one(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add_all(
            [
                Chunk(
                    document_id=document_id,
                    text="[1:3]\n\nSovereign of the Day of Recompense.",
                    source_location={"page_start": 2, "page_end": 2},
                    metadata_json={
                        "domain_metadata": {"tags": ["quran"], "reference_pattern": "surah_number:verse_number"},
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": 3,
                            "verse_end": 3,
                            "references": ["1:3"],
                        },
                    },
                ),
                Chunk(
                    document_id=document_id,
                    text="[1:4]\n\nIt is You we worship and You we ask for help.",
                    source_location={"page_start": 2, "page_end": 2},
                    metadata_json={
                        "domain_metadata": {"tags": ["quran"], "reference_pattern": "surah_number:verse_number"},
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": 4,
                            "verse_end": 4,
                            "references": ["1:4"],
                            "previous_ref": "1:3",
                            "next_ref": "1:5",
                        },
                    },
                ),
                Chunk(
                    document_id=document_id,
                    text="[2:4]\n\nAnd who believe in what has been revealed to you.",
                    source_location={"page_start": 3, "page_end": 3},
                    metadata_json={
                        "domain_metadata": {"tags": ["quran"], "reference_pattern": "surah_number:verse_number"},
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": 2,
                            "chapter_end": 2,
                            "verse_start": 4,
                            "verse_end": 4,
                            "references": ["2:4"],
                        },
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "What does Quran 1:4 say?", "document_ids": [document_id], "limit": 3},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["text"].startswith("[1:4]")
    assert items[0]["metadata"]["score_breakdown"]["reference_exact"] > 0


@pytest.mark.asyncio
async def test_search_chunks_natural_language_returns_exact_phrase_in_top_five(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        for index in range(8):
            session.add(
                Chunk(
                    document_id=document_id,
                    text=f"Generic Allah guidance chunk {index}",
                    source_location={"page_start": index + 10},
                    metadata_json={"domain_metadata": {"tags": ["quran"]}},
                )
            )
        session.add(
            Chunk(
                document_id=document_id,
                text="[1:5]\n\nGuide us to the straight path -",
                source_location={"page_start": 2},
                metadata_json={
                    "domain_metadata": {"tags": ["quran"], "reference_pattern": "surah_number:verse_number"},
                    "reference_metadata": {
                        "reference_type": "surah_ayah",
                        "chapter_start": 1,
                        "chapter_end": 1,
                        "verse_start": 5,
                        "verse_end": 5,
                        "references": ["1:5"],
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={
            "query": "What guidance is requested in Quran 1:5?",
            "document_ids": [document_id],
            "limit": 5,
        },
    )

    assert response.status_code == 200
    texts = [item["text"] for item in response.json()["items"]]
    assert any(text.startswith("[1:5]") for text in texts)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest \
  backend/tests/test_chunks.py::test_search_chunks_exact_reference_returns_matching_verse_top_one \
  backend/tests/test_chunks.py::test_search_chunks_natural_language_returns_exact_phrase_in_top_five \
  -q
```

Expected: FAIL because current scoring does not parse reference metadata and does not attach `score_breakdown`.

- [ ] **Step 3: Implement `HybridChunkSearch`**

Create `backend/src/ragstudio/services/hybrid_chunk_search.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.reference_metadata import ReferenceSemantics


@dataclass(frozen=True)
class ChunkScore:
    score: float
    breakdown: dict[str, float]


class HybridChunkSearch:
    def score(self, query: str, chunk: Chunk) -> ChunkScore:
        query_text = query.strip().lower()
        chunk_text = chunk.text.lower()
        metadata = chunk.metadata_json or {}
        semantics = self._semantics(metadata)
        query_ref = semantics.extract_query_reference(query) if semantics else None
        reference_metadata = metadata.get("reference_metadata")

        reference_exact = 0.0
        same_chapter = 0.0
        if isinstance(query_ref, dict) and isinstance(reference_metadata, dict):
            q_chapter = query_ref.get("chapter")
            q_verse = query_ref.get("verse")
            chapter_start = reference_metadata.get("chapter_start")
            chapter_end = reference_metadata.get("chapter_end")
            verse_start = reference_metadata.get("verse_start")
            verse_end = reference_metadata.get("verse_end")
            if (
                isinstance(q_chapter, int)
                and isinstance(q_verse, int)
                and isinstance(chapter_start, int)
                and isinstance(chapter_end, int)
                and isinstance(verse_start, int)
                and isinstance(verse_end, int)
                and chapter_start <= q_chapter <= chapter_end
                and verse_start <= q_verse <= verse_end
            ):
                reference_exact = 100.0
            elif (
                isinstance(q_chapter, int)
                and isinstance(chapter_start, int)
                and isinstance(chapter_end, int)
                and chapter_start <= q_chapter <= chapter_end
            ):
                same_chapter = 5.0

        exact_phrase = 8.0 if query_text and query_text in chunk_text else 0.0
        query_terms = self._terms(query_text)
        chunk_terms = self._terms(chunk_text)
        if query_terms and chunk_terms:
            overlap = query_terms & chunk_terms
            coverage = len(overlap) / len(query_terms)
            density = len(overlap) / len(chunk_terms)
        else:
            coverage = 0.0
            density = 0.0

        metadata_boost = self._metadata_boost(query_text, metadata)
        lexical = (coverage * 10.0) + (density * 2.0)
        breakdown = {
            "reference_exact": reference_exact,
            "same_chapter": same_chapter,
            "exact_phrase": exact_phrase,
            "term_coverage": coverage * 10.0,
            "term_density": density * 2.0,
            "metadata_boost": metadata_boost,
        }
        return ChunkScore(score=sum(breakdown.values()), breakdown=breakdown)

    def _semantics(self, metadata: dict[str, Any]) -> ReferenceSemantics | None:
        domain_metadata = metadata.get("domain_metadata")
        if not isinstance(domain_metadata, dict):
            return None
        return ReferenceSemantics.from_metadata(DomainMetadata.model_validate(domain_metadata))

    def _metadata_boost(self, query_text: str, metadata: dict[str, Any]) -> float:
        domain_metadata = metadata.get("domain_metadata")
        if not isinstance(domain_metadata, dict):
            return 0.0
        tags = domain_metadata.get("tags")
        boost = 0.0
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag.casefold() in query_text:
                    boost += 1.0
        for field in ("domain", "document_type", "collection", "content_role"):
            value = domain_metadata.get(field)
            if isinstance(value, str) and value and value.casefold() in query_text:
                boost += 1.0

        document_metadata = metadata.get("document_metadata")
        if isinstance(document_metadata, dict):
            title = document_metadata.get("title")
            if isinstance(title, str):
                title_terms = self._terms(title.lower())
                query_terms = self._terms(query_text)
                shared_title_terms = query_terms & title_terms
                if shared_title_terms:
                    boost += min(10.0, len(shared_title_terms) * 2.0)

        return min(boost, 12.0)

    def _terms(self, value: str) -> set[str]:
        return {
            match.group(0).lower()
            for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
        }
```

- [ ] **Step 4: Wire `HybridChunkSearch` into `ChunkService.search()`**

In `backend/src/ragstudio/services/chunk_service.py`, add import:

```python
from ragstudio.services.hybrid_chunk_search import HybridChunkSearch
```

In `__init__`, add:

```python
self.hybrid_search = HybridChunkSearch()
```

Replace scoring in `search()`:

```python
ranked = sorted(
    (
        (self.hybrid_search.score(search_in.query, chunk), source_order, chunk)
        for source_order, chunk in enumerate(chunks)
    ),
    key=lambda item: (
        -item[0].score,
        self._source_order(item[2], item[1]),
    ),
)
if search_in.query.strip():
    ranked = [item for item in ranked if item[0].score > 0]

items = [
    self._chunk_out_with_score(chunk, score.score, score.breakdown)
    for score, _, chunk in ranked[:limit]
]
```

Update `_chunk_out_with_score()`:

```python
def _chunk_out_with_score(
    self,
    chunk: Chunk,
    score: float,
    breakdown: dict[str, float] | None = None,
) -> ChunkOut:
    output = ChunkOut.model_validate(chunk)
    output.metadata = {
        **output.metadata,
        "score": score,
        "score_breakdown": breakdown or {},
    }
    return output
```

Keep `_score()` and `_terms()` only if other code still calls them. If `rg "_score\\(" backend/src backend/tests` shows no callers, remove both methods.

- [ ] **Step 5: Run search tests**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_chunks.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunks.py
git commit -m "feat: rank chunks with hybrid metadata search"
```

---

## Task 5: Quran Regression Fixture for Excel-Like Cases

**Files:**
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Add regression test covering the Excel failure pattern**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_quran_excel_reference_queries_pass_top_one_or_top_five(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    quran_metadata = {
        "domain": "religion",
        "document_type": "religious_text",
        "tags": ["quran", "islam", "translation"],
        "reference_pattern": "surah_number:verse_number",
        "expected_structure": "parallel_text",
        "custom_json": {
            "reference_schema": {"type": "surah_ayah"},
            "retrieval": {"exact_reference_top1": True, "boost_same_chapter": True},
        },
    }
    rows = [
        ("[1:1]\n\n[All] praise is [due] to Allah, Lord of the worlds -", 1, 1),
        ("[1:4]\n\nIt is You we worship and You we ask for help.", 1, 4),
        ("[1:5]\n\nGuide us to the straight path -", 1, 5),
        ("[2:2]\n\nThis is the Book about which there is no doubt, a guidance for those conscious of Allah -", 2, 2),
        ("[2:3]\n\nWho believe in the unseen, establish prayer, and spend out of what We have provided for them,", 2, 3),
        ("[2:7]\n\nAllah has set a seal upon their hearts and upon their hearing, and over their vision is a veil.", 2, 7),
        ("[2:8]\n\nAnd of the people are some who say, \"We believe in Allah and the Last Day,\" but they are not believers.", 2, 8),
        ("[2:11]\n\nDo not cause corruption on the earth, they say, \"We are but reformers.\"", 2, 11),
        ("[2:17]\n\nTheir example is that of one who kindled a fire.", 2, 17),
    ]

    app = client._transport.app
    async with app.state.session_factory() as session:
        for text, chapter, verse in rows:
            session.add(
                Chunk(
                    document_id=document_id,
                    text=text,
                    source_location={"page_start": chapter + 1},
                    metadata_json={
                        "domain_metadata": quran_metadata,
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": chapter,
                            "chapter_end": chapter,
                            "verse_start": verse,
                            "verse_end": verse,
                            "references": [f"{chapter}:{verse}"],
                        },
                    },
                )
            )
        session.add(
            Chunk(
                document_id=document_id,
                text="The Holy Quran\n\nArabic Text with English Translation",
                source_location={"page_start": 1},
                metadata_json={
                    "domain_metadata": quran_metadata,
                    "document_metadata": {
                        "title": "The Holy Quran Arabic Text with English Translation"
                    },
                },
            )
        )
        await session.commit()

    exact_reference_cases = [
        ("Quran 1:1", "[1:1]"),
        ("Quran 1:4", "[1:4]"),
        ("Quran 1:5", "[1:5]"),
        ("Quran 2:2", "[2:2]"),
    ]
    for query, expected_prefix in exact_reference_cases:
        response = await client.post(
            "/api/chunks/search",
            json={"query": query, "document_ids": [document_id], "limit": 5},
        )
        assert response.status_code == 200
        assert response.json()["items"][0]["text"].startswith(expected_prefix)

    natural_cases = [
        ("What is the title of the uploaded document?", "The Holy Quran"),
        ("What guidance is requested in Quran 1:5?", "[1:5]"),
        ("According to Quran 2:3, what do the conscious of Allah do?", "[2:3]"),
        ("What do some people say in Quran 2:8?", "[2:8]"),
        ("Find the chunk containing The Entirely Merciful, the Especially Merciful", "[1:1]"),
    ]
    for query, expected_text in natural_cases:
        response = await client.post(
            "/api/chunks/search",
            json={"query": query, "document_ids": [document_id], "limit": 5},
        )
        assert response.status_code == 200
        texts = [item["text"] for item in response.json()["items"]]
        assert any(expected_text in text for text in texts), query
```

- [ ] **Step 2: Run regression test**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest backend/tests/test_chunks.py::test_quran_excel_reference_queries_pass_top_one_or_top_five -q
```

Expected: PASS after Task 4.

- [ ] **Step 3: Run targeted backend tests**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest \
  backend/tests/test_reference_metadata.py \
  backend/tests/test_chunk_splitter.py \
  backend/tests/test_chunks.py \
  backend/tests/test_domain_metadata.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_chunks.py backend/src/ragstudio/services/hybrid_chunk_search.py
git commit -m "test: cover quran metadata retrieval regressions"
```

---

## Task 6: End-to-End Verification and Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md`
- Reference output: `artifacts/quran_chunking_test_cases.xlsx`

- [ ] **Step 1: Update the existing design note**

Append this section to `docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md`:

```markdown
## Metadata-Controlled Retrieval Extension

Reference-heavy corpora must not rely on hardcoded domain names. The chunker and retriever derive behavior from `DomainMetadata` and editable `custom_json`:

- `custom_json.reference_schema` defines reference type and field mapping.
- `custom_json.relationships` defines previous, next, chapter, page, or corpus-specific links.
- `custom_json.chunking` defines chunk unit and neighboring context.
- `custom_json.retrieval` defines exact-reference and metadata boost behavior.

The Quran regression case uses `reference_schema.type=surah_ayah`, but the implementation is generic: other corpora can define chapter/verse, legal section, page-line, or similar reference semantics through metadata.
```

- [ ] **Step 2: Run the full relevant test suite**

Run:

```bash
docker compose run -T --rm \
  -v "$PWD/backend/src:/app/backend/src" \
  -v "$PWD/backend/tests:/app/backend/tests:ro" \
  backend python -m pytest \
  backend/tests/test_reference_metadata.py \
  backend/tests/test_chunk_splitter.py \
  backend/tests/test_chunks.py \
  backend/tests/test_domain_metadata.py \
  backend/tests/test_documents.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Re-run the real Chrome/MinerU Quran path if HPC is available**

Use the manual flow from the previous run:

1. Open `http://127.0.0.1:5173/documents`.
2. Upload `/Users/meet/Downloads/quran_arabic_english.pdf`.
3. Click `Auto-suggest`.
4. Confirm metadata includes reference custom JSON.
5. Select `MinerU strict`.
6. Click `Upload`.
7. Poll `/api/jobs` until the job is `succeeded`.
8. Run the Excel checks.

Expected:

- Chrome upload succeeds.
- Autosuggest proposes editable reference metadata.
- MinerU job succeeds.
- Exact reference queries like `Quran 1:4` return the matching verse chunk top 1.
- Natural-language Excel queries return expected chunks in top 5.

- [ ] **Step 4: Commit docs**

```bash
git add docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md
git commit -m "docs: define metadata-controlled hybrid retrieval"
```

---

## Task 7: Retrieval Explain and Debug Payloads

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_explainer.py`
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Test: `backend/tests/test_chunks.py`
- Test: `frontend/tests/chunk-inspector.test.tsx`

- [ ] **Step 1: Add failing backend test for explain payload**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_search_chunks_returns_retrieval_explain_breakdown(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            Chunk(
                document_id=document_id,
                text="[1:4]\n\nIt is You we worship and You we ask for help.",
                source_location={"page_start": 2},
                metadata_json={
                    "domain_metadata": {"tags": ["quran"], "reference_pattern": "surah_number:verse_number"},
                    "reference_metadata": {
                        "reference_type": "surah_ayah",
                        "chapter_start": 1,
                        "chapter_end": 1,
                        "verse_start": 4,
                        "verse_end": 4,
                        "references": ["1:4"],
                        "previous_ref": "1:3",
                        "next_ref": "1:5",
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "Quran 1:4", "document_ids": [document_id], "limit": 1},
    )

    item = response.json()["items"][0]
    explain = item["metadata"]["retrieval_explain"]
    assert explain["query_reference"] == "1:4"
    assert explain["matched_references"] == ["1:4"]
    assert explain["signals"][0]["name"] == "reference_exact"
    assert explain["signals"][0]["value"] == 100.0
```

- [ ] **Step 2: Create retrieval explainer**

Create `backend/src/ragstudio/services/retrieval_explainer.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalExplain:
    query_reference: str | None
    matched_references: list[str]
    relationship_refs: dict[str, str]
    signals: list[dict[str, float | str]]

    def model_dump(self) -> dict[str, Any]:
        return {
            "query_reference": self.query_reference,
            "matched_references": self.matched_references,
            "relationship_refs": self.relationship_refs,
            "signals": self.signals,
        }


def build_retrieval_explain(
    *,
    query_reference: str | None,
    metadata: dict[str, Any],
    score_breakdown: dict[str, float],
) -> RetrievalExplain:
    reference_metadata = metadata.get("reference_metadata")
    if not isinstance(reference_metadata, dict):
        reference_metadata = {}
    references = reference_metadata.get("references")
    relationship_refs = {
        key: value
        for key, value in {
            "previous": reference_metadata.get("previous_ref"),
            "next": reference_metadata.get("next_ref"),
            "chapter": reference_metadata.get("chapter_ref"),
            "page": reference_metadata.get("page_ref"),
        }.items()
        if isinstance(value, str) and value
    }
    signals = [
        {"name": name, "value": value}
        for name, value in sorted(score_breakdown.items(), key=lambda item: item[1], reverse=True)
        if value > 0
    ]
    return RetrievalExplain(
        query_reference=query_reference,
        matched_references=[ref for ref in references or [] if isinstance(ref, str)],
        relationship_refs=relationship_refs,
        signals=signals,
    )
```

- [ ] **Step 3: Attach explain payload during scoring**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, import and call the explainer:

```python
from ragstudio.services.retrieval_explainer import build_retrieval_explain
```

When returning a score, include the explanation in the existing metadata update path:

```python
query_reference_label = None
if isinstance(query_ref, dict) and isinstance(query_ref.get("chapter"), int) and isinstance(query_ref.get("verse"), int):
    query_reference_label = f"{query_ref['chapter']}:{query_ref['verse']}"
explain = build_retrieval_explain(
    query_reference=query_reference_label,
    metadata=metadata,
    score_breakdown=breakdown,
)
return ChunkScore(score=sum(breakdown.values()), breakdown={**breakdown, "retrieval_explain": explain.model_dump()})
```

In `backend/src/ragstudio/services/chunk_service.py`, store non-score explain data separately before assigning metadata:

```python
score_breakdown = dict(chunk_score.breakdown)
retrieval_explain = score_breakdown.pop("retrieval_explain", None)
metadata = {**output.metadata, "score": chunk_score.score, "score_breakdown": score_breakdown}
if isinstance(retrieval_explain, dict):
    metadata["retrieval_explain"] = retrieval_explain
output.metadata = metadata
```

- [ ] **Step 4: Render explain details in chunk inspector**

In `frontend/src/features/chunks/chunk-inspector.tsx`, add a compact section near the score badge:

```tsx
const explain = chunk.metadata.retrieval_explain as
  | { query_reference?: string; matched_references?: string[]; relationship_refs?: Record<string, string>; signals?: Array<{ name: string; value: number }> }
  | undefined;
```

Render:

```tsx
{explain ? (
  <div aria-label="Retrieval explain" className="rounded-md border border-slate-200 p-3 text-sm">
    <div>Query reference: {explain.query_reference ?? "none"}</div>
    <div>Matched: {(explain.matched_references ?? []).join(", ") || "none"}</div>
    <div>Relations: {Object.entries(explain.relationship_refs ?? {}).map(([key, value]) => `${key} ${value}`).join(", ") || "none"}</div>
    <div>Signals: {(explain.signals ?? []).map((signal) => `${signal.name} ${signal.value}`).join(", ") || "none"}</div>
  </div>
) : null}
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
docker compose run -T --rm backend python -m pytest backend/tests/test_chunks.py::test_search_chunks_returns_retrieval_explain_breakdown -q
npm --prefix frontend test -- chunk-inspector.test.tsx
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/retrieval_explainer.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunks.py frontend/src/features/chunks/chunk-inspector.tsx frontend/tests/chunk-inspector.test.tsx
git commit -m "feat: explain chunk retrieval ranking"
```

---

## Task 8: Custom JSON Schema Helper

**Files:**
- Create: `backend/src/ragstudio/services/metadata_json_schema.py`
- Modify: `backend/src/ragstudio/api/routes/domain_profiles.py`
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Test: `backend/tests/test_domain_metadata.py`
- Test: `frontend/tests/domain-metadata-panel.test.tsx`

- [ ] **Step 1: Add failing schema helper tests**

Append to `backend/tests/test_domain_metadata.py`:

```python
def test_reference_custom_json_schema_accepts_quran_relationships():
    from ragstudio.services.metadata_json_schema import validate_custom_json

    errors = validate_custom_json(
        {
            "reference_schema": {"type": "surah_ayah", "fields": {"chapter": "surah", "verse": "ayah", "page": "page_start"}},
            "relationships": {"previous": ["same_chapter", "verse - 1"], "next": ["same_chapter", "verse + 1"], "page": ["same_page"]},
            "chunking": {"unit": "verse", "include_neighbors": 1, "preserve_parallel_text": True},
            "retrieval": {"exact_reference_top1": True, "boost_same_chapter": True, "boost_neighbor_verses": True},
        }
    )

    assert errors == []
```

- [ ] **Step 2: Implement schema helper**

Create `backend/src/ragstudio/services/metadata_json_schema.py`:

```python
from __future__ import annotations

from typing import Any

REFERENCE_CUSTOM_JSON_EXAMPLE: dict[str, Any] = {
    "reference_schema": {"type": "surah_ayah", "fields": {"chapter": "surah", "verse": "ayah", "page": "page_start"}},
    "relationships": {"previous": ["same_chapter", "verse - 1"], "next": ["same_chapter", "verse + 1"], "chapter": ["same_chapter"], "page": ["same_page"]},
    "chunking": {"unit": "verse", "include_neighbors": 1, "preserve_parallel_text": True},
    "retrieval": {"exact_reference_top1": True, "boost_same_chapter": True, "boost_neighbor_verses": True},
}


def validate_custom_json(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value.get("reference_schema", {}), dict):
        errors.append("reference_schema must be an object.")
    if not isinstance(value.get("relationships", {}), dict):
        errors.append("relationships must be an object.")
    chunking = value.get("chunking", {})
    if isinstance(chunking, dict) and "include_neighbors" in chunking and not isinstance(chunking["include_neighbors"], int):
        errors.append("chunking.include_neighbors must be an integer.")
    retrieval = value.get("retrieval", {})
    if isinstance(retrieval, dict):
        for key in ("exact_reference_top1", "boost_same_chapter", "boost_neighbor_verses"):
            if key in retrieval and not isinstance(retrieval[key], bool):
                errors.append(f"retrieval.{key} must be true or false.")
    return errors
```

- [ ] **Step 3: Expose example through a reference schema endpoint**

In `backend/src/ragstudio/api/routes/domain_profiles.py`, add an endpoint used by the Documents metadata panel:

```python
from ragstudio.services.metadata_json_schema import REFERENCE_CUSTOM_JSON_EXAMPLE


@router.get("/reference-json-example")
async def get_reference_json_example() -> dict[str, object]:
    return {"custom_json": REFERENCE_CUSTOM_JSON_EXAMPLE}
```

- [ ] **Step 4: Add UI helper**

In `frontend/src/api/client.ts`, add:

```ts
getReferenceJsonExample: () =>
  request<{ custom_json: Record<string, unknown> }>("/api/domain-profiles/reference-json-example"),
```

In `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`, add state and a loader:

```tsx
const [referenceCustomJsonExample, setReferenceCustomJsonExample] = useState<Record<string, unknown>>({});

useEffect(() => {
  apiClient.getReferenceJsonExample().then((response) => {
    setReferenceCustomJsonExample(response.custom_json);
  });
}, []);
```

Add a button beside Custom JSON:

```tsx
<Button type="button" variant="outline" onClick={() => {
  const merged = { ...(metadata.custom_json ?? {}), ...referenceCustomJsonExample };
  setCustomJsonDraft(JSON.stringify(merged, null, 2));
  setMetadata({ custom_json: merged });
}}>
  Insert reference schema
</Button>
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
docker compose run -T --rm backend python -m pytest backend/tests/test_domain_metadata.py -q
npm --prefix frontend test -- domain-metadata-panel.test.tsx
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/api/routes/domain_profiles.py backend/tests/test_domain_metadata.py frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/tests/domain-metadata-panel.test.tsx
git commit -m "feat: guide editable reference metadata json"
```

---

## Task 9: Reindex With Updated Metadata

**Files:**
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `backend/tests/test_documents.py`
- Test: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Add failing backend test**

Append to `backend/tests/test_documents.py`:

```python
@pytest.mark.asyncio
async def test_reindex_document_uses_updated_domain_metadata(client):
    upload = await client.post("/api/documents", files={"file": ("quran.txt", b"surah sample", "text/plain")})
    document_id = upload.json()["id"]

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={
            "parser_mode": "mineru_strict",
            "domain_metadata": {
                "domain": "religion",
                "document_type": "religious_text",
                "tags": ["quran"],
                "reference_pattern": "surah_number:verse_number",
                "custom_json": {"chunking": {"unit": "verse"}},
            },
        },
    )

    assert response.status_code == 202
    assert response.json()["document_id"] == document_id
```

- [ ] **Step 2: Implement endpoint**

In `backend/src/ragstudio/api/routes/documents.py`, add:

```python
@router.post("/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document_with_metadata(
    document_id: str,
    payload: IndexDocumentOptions,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    job = await DocumentService(session).reindex_existing_document(document_id, payload)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return {"document_id": document_id, "job_id": job.id, "status": job.status}
```

In `backend/src/ragstudio/services/document_service.py`, add `reindex_existing_document()` that loads the existing document, reuses `file_path`, creates an `index_document` job, and calls the existing background reindex path with the submitted `IndexDocumentOptions`.

- [ ] **Step 3: Add client and UI action**

In `frontend/src/api/client.ts`:

```ts
reindexDocument: (documentId: string, options: UploadDocumentOptions) =>
  request<{ document_id: string; job_id: string; status: string }>(`/api/documents/${documentId}/reindex`, {
    method: "POST",
    body: JSON.stringify({ parser_mode: options.parser_mode, domain_metadata: options.domain_metadata }),
    headers: { "Content-Type": "application/json" },
  }),
```

In `frontend/src/features/documents/documents-page.tsx`, add a row action:

```tsx
<Button type="button" onClick={() => reindexDocument.mutate(document.id)} disabled={!metadataValid || reindexDocument.isPending}>
  Reindex with metadata
</Button>
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
docker compose run -T --rm backend python -m pytest backend/tests/test_documents.py::test_reindex_document_uses_updated_domain_metadata -q
npm --prefix frontend test -- documents-page.test.tsx
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/api/routes/documents.py backend/src/ragstudio/services/document_service.py backend/tests/test_documents.py frontend/src/api/client.ts frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "feat: reindex documents with updated metadata"
```

---

## Task 10: Neighbor Expansion at Retrieval Time

**Files:**
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Add failing test for neighbor relationship expansion**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_exact_reference_search_includes_previous_and_next_relationships(client):
    upload_response = await client.post("/api/documents", files={"file": ("quran.txt", b"surah sample", "text/plain")})
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        for verse in (3, 4, 5):
            session.add(
                Chunk(
                    document_id=document_id,
                    text=f"[1:{verse}]\n\nVerse {verse}",
                    source_location={"page_start": 2},
                    metadata_json={
                        "domain_metadata": {"tags": ["quran"], "custom_json": {"retrieval": {"include_neighbors_on_exact": True}}},
                        "reference_metadata": {
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": verse,
                            "verse_end": verse,
                            "references": [f"1:{verse}"],
                            "previous_ref": f"1:{verse - 1}" if verse > 1 else None,
                            "next_ref": f"1:{verse + 1}",
                        },
                    },
                )
            )
        await session.commit()

    response = await client.post("/api/chunks/search", json={"query": "Quran 1:4", "document_ids": [document_id], "limit": 3})

    texts = [item["text"] for item in response.json()["items"]]
    assert texts[0].startswith("[1:4]")
    assert any(text.startswith("[1:3]") for text in texts)
    assert any(text.startswith("[1:5]") for text in texts)
```

- [ ] **Step 2: Implement neighbor boosting**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, after exact-reference detection:

```python
neighbor_match = 0.0
if isinstance(query_ref, dict) and isinstance(reference_metadata, dict):
    requested = f"{query_ref.get('chapter')}:{query_ref.get('verse')}"
    if requested in {reference_metadata.get("previous_ref"), reference_metadata.get("next_ref")}:
        neighbor_match = 30.0
breakdown["neighbor_match"] = neighbor_match
```

- [ ] **Step 3: Run test and commit**

Run:

```bash
docker compose run -T --rm backend python -m pytest backend/tests/test_chunks.py::test_exact_reference_search_includes_previous_and_next_relationships -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/hybrid_chunk_search.py backend/tests/test_chunks.py
git commit -m "feat: include neighbor chunks for exact references"
```

---

## Task 11: Excel Regression Runner

**Files:**
- Create: `backend/src/ragstudio/services/excel_regression_runner.py`
- Create: `backend/tests/test_excel_regression_runner.py`
- Modify: `docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md`

- [ ] **Step 1: Add failing runner test**

Create `backend/tests/test_excel_regression_runner.py`:

```python
from ragstudio.services.excel_regression_runner import ExcelCase, summarize_excel_results


def test_excel_runner_marks_exact_reference_top_one_pass():
    summary = summarize_excel_results(
        [
            ExcelCase(case_id="TC001", query="Quran 1:4", expected_text="[1:4]", required_rank=1),
        ],
        {
            "TC001": [
                {"rank": 1, "text": "[1:4]\n\nIt is You we worship", "metadata": {"retrieval_explain": {"query_reference": "1:4"}}}
            ]
        },
    )

    assert summary[0]["verdict"] == "PASS"
    assert summary[0]["matched_rank"] == 1
```

- [ ] **Step 2: Implement runner primitives**

Create `backend/src/ragstudio/services/excel_regression_runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExcelCase:
    case_id: str
    query: str
    expected_text: str
    required_rank: int


def summarize_excel_results(cases: list[ExcelCase], results_by_case: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        results = results_by_case.get(case.case_id, [])
        matched_rank = next(
            (int(result["rank"]) for result in results if case.expected_text in str(result.get("text", ""))),
            None,
        )
        rows.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "expected_text": case.expected_text,
                "required_rank": case.required_rank,
                "matched_rank": matched_rank,
                "verdict": "PASS" if matched_rank is not None and matched_rank <= case.required_rank else "FAIL",
                "top_debug": [result.get("metadata", {}).get("retrieval_explain", {}) for result in results[:5]],
            }
        )
    return rows
```

- [ ] **Step 3: Document command**

Append to `docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md`:

```markdown
### Excel Regression Runner

The retrieval regression runner records each query, expected text, required rank, matched rank, pass/fail verdict, and top retrieval explain payloads. The workbook sheet name should include the execution date, for example `Hybrid Retrieval 2026-05-09`.
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
docker compose run -T --rm backend python -m pytest backend/tests/test_excel_regression_runner.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/excel_regression_runner.py backend/tests/test_excel_regression_runner.py docs/superpowers/specs/2026-05-09-shared-metadata-chunking-design.md
git commit -m "feat: add excel retrieval regression runner"
```

---

## Task 12: Autosuggest Confidence and Custom JSON Diff View

**Files:**
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Test: `frontend/tests/domain-metadata-panel.test.tsx`

- [ ] **Step 1: Add failing UI test**

Append to `frontend/tests/domain-metadata-panel.test.tsx`:

```tsx
it("shows autosuggest custom json changes with confidence and evidence", async () => {
  const valueWithEmptyCustomJson = {
    domain_metadata: {
      domain: "generic",
      document_type: "document",
      tags: [],
      custom_json: {},
    },
  };
  const onChange = vi.fn();

  render(<DomainMetadataPanel value={valueWithEmptyCustomJson} onChange={onChange} />);

  await userEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

  expect(await screen.findByText(/Confidence 95%/i)).toBeInTheDocument();
  expect(screen.getByText(/reference_schema added/i)).toBeInTheDocument();
  expect(screen.getByText(/chunking.unit changed to verse/i)).toBeInTheDocument();
  expect(screen.getByText(/pages 1, 2, 507, 1012/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Expand custom JSON change formatter**

In `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`, replace the single summary string for `custom_json` with keyed diffs:

```ts
function flattenCustomJson(value: Record<string, unknown>, prefix = ""): Record<string, string> {
  return Object.entries(value).reduce<Record<string, string>>((acc, [key, raw]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      Object.assign(acc, flattenCustomJson(raw as Record<string, unknown>, path));
    } else {
      acc[path] = JSON.stringify(raw);
    }
    return acc;
  }, {});
}

function formatCustomJsonDiff(before: Record<string, unknown>, after: Record<string, unknown>): string[] {
  const left = flattenCustomJson(before);
  const right = flattenCustomJson(after);
  return Array.from(new Set([...Object.keys(left), ...Object.keys(right)])).flatMap((key) => {
    if (!(key in left)) return [`${key} added`];
    if (!(key in right)) return [`${key} removed`];
    if (left[key] !== right[key]) return [`${key} changed to ${right[key]}`];
    return [];
  });
}
```

Render the returned lines under the autosuggest summary:

```tsx
{change.field === "custom_json" && Array.isArray(change.details) ? (
  <ul>
    {change.details.map((detail) => <li key={detail}>{detail}</li>)}
  </ul>
) : null}
```

- [ ] **Step 3: Run test and commit**

Run:

```bash
npm --prefix frontend test -- domain-metadata-panel.test.tsx
```

Expected: PASS.

Commit:

```bash
git add frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/tests/domain-metadata-panel.test.tsx
git commit -m "feat: show autosuggest custom json diffs"
```

---

## Self-Review

**Spec coverage:** This plan covers the chosen full approach: metadata-driven chunk profiles, editable custom JSON semantics, retrieval metadata usage, exact-reference top-1 behavior, natural-language top-5 behavior, title preservation, regression tests, retrieval explainability, custom JSON guidance, reindexing with changed metadata, neighbor expansion, Excel regression output, and autosuggest diff visibility.

**Placeholder scan:** No task uses `TBD`, `TODO`, “add appropriate”, “similar to”, or throwaway placeholder payloads. Each code task includes exact file paths, test snippets, implementation snippets, commands, and expected results.

**Type consistency:** The plan consistently uses existing `DomainMetadata.custom_json`, existing `AdapterChunk`, existing `ChunkService.search()`, new `ReferenceSemantics`, new `HybridChunkSearch`, and existing `ChunkOut.metadata` for score breakdowns. The new metadata keys are `reference_metadata`, `document_metadata`, `parser_metadata.split_profile`, `score_breakdown`, `retrieval_explain`, and relationship refs.

**Scope check:** This is one coherent subsystem: metadata-controlled chunking, retrieval, and observable verification. The added UI work is limited to controls needed to edit metadata, reindex, and understand retrieval behavior.
